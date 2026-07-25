"""
Routeur d'intentions Néron -- module d'inférence.

Architecture hybride (décision du 24/07) :
  1. Le classifieur CamemBERT (mean pooling) prédit `target` (domaine).
  2. Si target == "homeassistant" ET l'operation concerne lumière/volet :
     une règle lexicale déterministe tranche la polarité (allume/éteins,
     ouvre/ferme) -- le classifieur ML a plafonné/régressé sur ces 4 classes
     malgré l'enrichissement de données (0.42-0.67 f1), alors qu'une règle
     sur le verbe est fiable et ne nécessite aucun exemple d'entraînement.
  3. Sinon, le classifieur CamemBERT (CLS pooling) prédit `operation`
     directement.

Usage :
    from neron_intent_classifier import IntentRouter
    router = IntentRouter()
    result = router.route("Éteins la lumière du salon")
    # {"target": "homeassistant", "operation": "turn_off_light", "method": "lexical_rule"}
"""
import os
import re

import joblib
import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

MODEL_ID = "camembert-base"
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
    def __init__(self, target_clf_path=_DEFAULT_TARGET_CLF,
                 operation_clf_path=_DEFAULT_OPERATION_CLF):
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        self.model = AutoModel.from_pretrained(MODEL_ID, dtype=torch.float32)
        self.model.eval()
        self.target_clf = joblib.load(target_clf_path)
        self.operation_clf = joblib.load(operation_clf_path)

    def _embed_mean(self, text: str) -> np.ndarray:
        inputs = self.tokenizer([text], return_tensors="pt", padding=True, truncation=True)
        with torch.no_grad():
            outputs = self.model(**inputs)
        hidden = outputs.last_hidden_state
        mask = inputs["attention_mask"].unsqueeze(-1).float()
        summed = (hidden * mask).sum(dim=1)
        counts = mask.sum(dim=1).clamp(min=1e-9)
        return (summed / counts).numpy()

    def _embed_cls(self, text: str) -> np.ndarray:
        inputs = self.tokenizer([text], return_tensors="pt", padding=True, truncation=True)
        with torch.no_grad():
            outputs = self.model(**inputs)
        return outputs.last_hidden_state[:, 0, :].numpy()

    def route(self, phrase: str) -> dict:
        target = self.target_clf.predict(self._embed_mean(phrase))[0]

        if target == "homeassistant":
            operation = _lexical_homeassistant_operation(phrase)
            if operation is not None:
                return {"target": target, "operation": operation, "method": "lexical_rule"}
            # Filet de sécurité : aucun mot-clé reconnu, on retombe sur le classifieur ML
            operation = self.operation_clf.predict(self._embed_cls(phrase))[0]
            return {"target": target, "operation": operation, "method": "ml_fallback"}

        operation = self.operation_clf.predict(self._embed_cls(phrase))[0]
        return {"target": target, "operation": operation, "method": "ml_classifier"}


if __name__ == "__main__":
    # Test rapide sur quelques phrases, y compris les cas ambigus qui posaient
    # problème au classifieur pur (allume/éteins, ouvre/ferme)
    router = IntentRouter()
    test_phrases = [
        "Allume la lumière du salon",
        "Éteins la lampe du bureau",
        "Ouvre les volets de la chambre",
        "Ferme les rideaux du salon",
        "Où en es-tu de tes objectifs ?",
        "Souviens-toi que j'ai rendez-vous à 15h",
        "Redémarre le service memory",
    ]
    for p in test_phrases:
        result = router.route(p)
        print(f"{p!r:55s} -> {result}")
