"""
Routeur d'intentions Néron -- module d'inférence CamemBERT.

Architecture hybride (décision du 24/07) :
  1. Le classifieur CamemBERT (mean pooling) prédit `target` (domaine).
  2. Si target == "homeassistant" ET l'operation concerne lumière/volet :
     une règle lexicale déterministe tranche la polarité (allume/éteins,
     ouvre/ferme) -- le classifieur ML a plafonné sur ces 4 classes
     (0.42-0.67 f1), alors qu'une règle sur le verbe est fiable.
  3. Sinon, le classifieur CamemBERT (CLS pooling) prédit `operation`.

Validé en holdout à 83.1 % target+operation (7259a53). Perdu lors de la
réintégration du Core (58ab382), rétabli ici avec quatre changements :

  - modèle `almanach/camembert-base` : l'identifiant historique
    `camembert-base` ne résout plus sur HuggingFace. Configurable
    (`intent_classifier.model` dans neron.yaml ou NERON_INTENT_CLASSIFIER_MODEL),
    y compris vers un dossier local pour un serveur sans accès réseau ;
  - un seul passage dans le modèle par phrase (mean ET CLS sont lus sur la
    même sortie) au lieu de deux : latence divisée par deux, prédictions
    identiques ;
  - chargement unique par processus (`get_ml_router`), sous verrou ;
  - indisponibilité tolérée : si le modèle ou ses dépendances manquent,
    `get_ml_router()` renvoie None, le routeur garde sa cascade de mots-clés.

Coût mesuré sur la Homebox (2 cœurs, sans GPU, 20/11/2026) : ~495 Mo de RAM,
~5,6 s de chargement, ~190 ms par phrase avec deux passages.

Pré-téléchargement sur un nouveau serveur (utilisateur du service) :
    huggingface-cli download almanach/camembert-base
"""
from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any

logger = logging.getLogger("core.pipeline.intent.ml")

DEFAULT_MODEL_ID = "almanach/camembert-base"
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_TARGET_CLF = os.path.join(_MODULE_DIR, "target_clf.joblib")
_DEFAULT_OPERATION_CLF = os.path.join(_MODULE_DIR, "operation_clf.joblib")

# Règle lexicale pour la polarité domotique (lumière/volet).
# Ordre important : les motifs les plus spécifiques d'abord.
_LIGHT_KEYWORDS = r"lumi[eè]re|lampe|[eé]clairage|[eé]claire"
_COVER_KEYWORDS = r"volet|rideau|store|fen[eê]tre"

_TURN_ON_VERBS = r"allume|active|d[eé]clenche|d[eé]marre"
_TURN_OFF_VERBS = r"[eé]teins|[eé]teindre|coupe|stoppe|stopper"
_OPEN_VERBS = r"ouvre|ouvrir|l[eè]ve|remonte|d[eé]gage"
_CLOSE_VERBS = r"ferme|fermer|baisse|descend|rabaisse|obscurcis"


def _lexical_homeassistant_operation(phrase: str) -> str | None:
    """
    Détecte la polarité d'une commande domotique (lumière/volet) par mots-clés.
    Retourne None si aucun motif ne matche -- dans ce cas, retomber sur le
    classifieur ML comme filet de sécurité (voir IntentRouter.route).
    """
    text = phrase.lower()

    is_light = re.search(_LIGHT_KEYWORDS, text) is not None
    is_cover = re.search(_COVER_KEYWORDS, text) is not None

    if re.search(_TURN_ON_VERBS, text) and (is_light or not is_cover):
        return "turn_on_light"
    if re.search(_TURN_OFF_VERBS, text) and (is_light or not is_cover):
        return "turn_off_light"
    if re.search(_OPEN_VERBS, text) and (is_cover or not is_light):
        return "open_cover"
    if re.search(_CLOSE_VERBS, text) and (is_cover or not is_light):
        return "close_cover"

    return None


class IntentRouter:
    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        target_clf_path: str = _DEFAULT_TARGET_CLF,
        operation_clf_path: str = _DEFAULT_OPERATION_CLF,
    ) -> None:
        import joblib
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModel.from_pretrained(model_id, dtype=torch.float32)
        self.model.eval()
        self.target_clf = joblib.load(target_clf_path)
        self.operation_clf = joblib.load(operation_clf_path)

    def _embed(self, text: str) -> tuple[Any, Any]:
        """Un seul passage : (mean pooling, CLS pooling)."""
        inputs = self.tokenizer([text], return_tensors="pt", padding=True, truncation=True)
        with self._torch.no_grad():
            hidden = self.model(**inputs).last_hidden_state
        mask = inputs["attention_mask"].unsqueeze(-1).float()
        mean = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
        cls = hidden[:, 0, :]
        return mean.numpy(), cls.numpy()

    def route(self, phrase: str) -> dict:
        mean, cls = self._embed(phrase)
        target = self.target_clf.predict(mean)[0]

        if target == "homeassistant":
            operation = _lexical_homeassistant_operation(phrase)
            if operation is not None:
                return {"target": target, "operation": operation, "method": "lexical_rule"}
            # Filet de sécurité : aucun mot-clé reconnu, on retombe sur le classifieur ML
            operation = self.operation_clf.predict(cls)[0]
            return {"target": target, "operation": operation, "method": "ml_fallback"}

        operation = self.operation_clf.predict(cls)[0]
        return {"target": target, "operation": operation, "method": "ml_classifier"}


# ---------------------------------------------------------------------------
# Instance unique par processus
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_router: IntentRouter | None = None
_unavailable_reason: str | None = None


def _enabled() -> bool:
    """NERON_INTENT_CLASSIFIER (0/1) prime sur neron.yaml, pour que tests et CI
    puissent le couper sans télécharger le modèle."""
    env = os.getenv("NERON_INTENT_CLASSIFIER", "").strip().lower()
    if env:
        return env not in {"0", "false", "no", "off"}
    try:
        from core.config import settings

        return bool(settings.INTENT_CLASSIFIER_ENABLED)
    except Exception:
        return True


def _model_id() -> str:
    try:
        from core.config import settings

        return str(settings.INTENT_CLASSIFIER_MODEL or DEFAULT_MODEL_ID)
    except Exception:
        return DEFAULT_MODEL_ID


def get_ml_router() -> IntentRouter | None:
    """Classifieur chargé, ou None s'il est désactivé ou indisponible.

    Bloquant au premier appel (~5 s) : à appeler hors de la boucle asyncio
    (asyncio.to_thread). L'échec n'est tenté qu'une fois par processus.
    """
    global _router, _unavailable_reason
    if _router is not None:
        return _router
    if not _enabled():
        return None
    with _lock:
        if _router is not None or _unavailable_reason is not None:
            return _router
        try:
            _router = IntentRouter(model_id=_model_id())
            logger.info("intent_classifier_loaded model=%s", _model_id())
        except Exception as exc:  # modèle absent, RAM, dépendances...
            _unavailable_reason = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "intent_classifier_unavailable model=%s reason=%s "
                "-- routage par mots-clés seul",
                _model_id(),
                _unavailable_reason,
            )
    return _router


def classifier_status() -> dict[str, Any]:
    return {
        "enabled": _enabled(),
        "loaded": _router is not None,
        "model": _model_id(),
        "unavailable_reason": _unavailable_reason,
    }
