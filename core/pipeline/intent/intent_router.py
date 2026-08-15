from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict

from core.agent_registry import get_logger
from core.pipeline.nlp.french_normalizer import normalize_text

logger = get_logger(__name__)


def _normalize(text: str) -> str:
    return normalize_text(text)


class Intent(str, Enum):
    CONVERSATION         = "conversation"
    GREETING             = "greeting"
    THANKS               = "thanks"
    GOODBYE              = "goodbye"
    STATUS_SMALLTALK     = "status_smalltalk"
    WEB_SEARCH           = "web_search"
    HA_ACTION            = "ha_action"
    TIME_QUERY           = "time_query"
    PERSONALITY_FEEDBACK = "personality_feedback"
    CODE                 = "code"
    CODE_AUDIT           = "code_audit"

    AGENT_CREATION       = "agent_creation"
    TOOL_CREATION        = "tool_creation"
    AGENT_LIST           = "agent_list"
    AGENT_RUN            = "agent_run"
    AGENT_ENABLE         = "agent_enable"
    AGENT_DISABLE        = "agent_disable"
    AGENT_DELETE         = "agent_delete"
    PROJECT_STATUS       = "project_status"
    PROJECT_LIST         = "project_list"

    SYSTEM_STATUS        = "system_status"
    NETWORK_STATUS       = "network_status"
    IDENTITY_QUERY       = "identity_query"
    SELF_STATUS          = "self_status"
    MEMORY_SEARCH        = "memory_search"
    REGISTRY_LIST       = "registry_list"
    REGISTRY_STATUS     = "registry_status"
    TOPOLOGY_SHOW       = "topology_show"

    NEWS_QUERY           = "news_query"
    WEATHER_QUERY        = "weather_query"
    TODO_ACTION          = "todo_action"
    WIKI_QUERY           = "wiki_query"


@dataclass
class IntentResult:
    intent: Intent
    confidence: str
    confidence_score: float = 0.0
    entities: Dict[str, Any] = field(default_factory=dict)

    def to_nlp_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent.value,
            "entities": self.entities,
            "confidence": self.confidence_score,
        }


# ---------------------------------------------------------------------------
# Mapping target/operation (classifieur CamemBERT) -> Intent (enum existant)
#
# Décisions de mapping (24/07) :
#   - homeassistant/* -> HA_ACTION. La polarité exacte (turn_on_light,
#     turn_off_light, open_cover, close_cover, get_temperature) est TOUJOURS
#     placée dans entities["operation"] -- HA_ACTION seul ne la porte pas,
#     donc tout handler qui a besoin de la distinction on/off doit lire
#     entities, pas juste intent.value.
#   - memory/remember, memory/forget -> CONVERSATION. Choix aligné sur le
#     comportement déjà en place dans l'ancien intent_router.py, qui
#     renvoyait volontairement CONVERSATION pour les requêtes mémoire et
#     laissait le Core orchestrator décider de l'action réelle en aval.
#   - goal/get_status -> PROJECT_STATUS, goal/create_agent -> AGENT_CREATION.
#     Mapping direct, pas d'ambiguïté.
#   - system/get_logs, system/restart_service, system/backup -> SYSTEM_STATUS.
#     ATTENTION : approximation la plus fragile de ce mapping. SYSTEM_STATUS
#     est sémantiquement une consultation ; backup et restart_service sont
#     des actions. Si un handler SYSTEM_STATUS ne lit jamais entities, une
#     demande de sauvegarde/redémarrage n'aura aucun effet visible. A vérifier
#     côté handler avant mise en prod, pas juste supposer que ça passe.
#   - conversation/start_conversation -> CONVERSATION.
#   - unknown/unknown -> CONVERSATION (repli, cohérent avec le comportement
#     par défaut de l'ancien routeur pour les cas non reconnus).
# ---------------------------------------------------------------------------

_TARGET_OPERATION_TO_INTENT: Dict[tuple[str, str], Intent] = {
    ("homeassistant", "turn_on_light"): Intent.HA_ACTION,
    ("homeassistant", "turn_off_light"): Intent.HA_ACTION,
    ("homeassistant", "open_cover"): Intent.HA_ACTION,
    ("homeassistant", "close_cover"): Intent.HA_ACTION,
    ("homeassistant", "get_temperature"): Intent.HA_ACTION,
    ("memory", "remember"): Intent.CONVERSATION,
    ("memory", "forget"): Intent.CONVERSATION,
    ("goal", "get_status"): Intent.PROJECT_STATUS,
    ("goal", "create_agent"): Intent.AGENT_CREATION,
    ("system", "get_logs"): Intent.SYSTEM_STATUS,
    ("system", "restart_service"): Intent.SYSTEM_STATUS,
    ("system", "backup"): Intent.SYSTEM_STATUS,
    ("conversation", "start_conversation"): Intent.CONVERSATION,
    ("unknown", "unknown"): Intent.CONVERSATION,
}


def _map_to_intent(target: str, operation: str) -> Intent:
    return _TARGET_OPERATION_TO_INTENT.get((target, operation), Intent.CONVERSATION)


# ---------------------------------------------------------------------------
# Cascade de mots-clés restaurée (24/07) -- UNIQUEMENT pour les intents sans
# équivalent dans le schéma target/operation du classifieur ML. Les domaines
# où le classifieur a été validé (homeassistant/memory/goal/system/
# conversation) ne passent PAS par ici, pour ne pas défaire le travail de
# validation du 24/07 -- cette cascade est un COMPLÉMENT, pas un remplacement.
# Vérifiée en premier (rapide, déterministe, pas d'appel LLM) ; si rien ne
# matche, on retombe sur le classifieur ML comme avant.
# ---------------------------------------------------------------------------

_GREETING_KEYWORDS = {
    "salut", "salut neron", "bonjour", "bonjour neron", "hello", "hello neron",
    "coucou", "coucou neron", "hey", "hey neron", "tu es la", "tu es la neron",
    "neron tu es la",
}
_THANKS_KEYWORDS = {"merci", "merci neron", "thanks", "thank you"}
_GOODBYE_KEYWORDS = {"au revoir", "bye", "a plus", "à plus", "bonne nuit"}
_STATUS_SMALLTALK_KEYWORDS = {
    "ca va", "ça va", "tu vas bien", "comment vas tu", "comment vas-tu",
}
_IDENTITY_KEYWORDS = [
    "qui es tu", "qui es-tu", "tu es qui", "presente toi", "présente toi",
    "presente-toi", "présente-toi", "quel est ton nom",
    "comment tu t appelles", "comment tu t'appelles",
]
_SELF_STATUS_KEYWORDS = [
    "etat interne", "etat conscience", "etat cognitif", "self status",
    "self model", "selfmodel", "que sais tu de toi", "que sais-tu de toi",
    "tes capacites", "tes capacités",
]
_TOPOLOGY_KEYWORDS = [
    "montre moi la topologie", "montre la topologie", "topologie du systeme",
    "affiche la topologie", "voir la topologie", "schema du systeme",
]
_REGISTRY_STATUS_KEYWORDS = [
    "quels services sont arretes", "services arretes", "services hors ligne",
    "services down",
]
_REGISTRY_LIST_KEYWORDS = [
    "quels services sont enregistres", "services enregistres",
    "quel service fournit les llm", "quel service fournit le llm",
    "quel service gere home assistant", "quel service gere la memoire",
]
_NETWORK_KEYWORDS = ["ports ouverts", "etat reseau", "status reseau"]
_TIME_KEYWORDS = [
    "quelle heure", "heure est il", "il est quelle heure",
    "dis moi quelle heure",
]
_WEATHER_KEYWORDS = [
    "meteo", "temperature", "temps demain", "prevision meteo",
    "previsions meteo",
]
_NEWS_KEYWORDS = ["actualite", "actualites", "news", "infos du jour", "information du jour"]
_CODE_AUDIT_KEYWORDS = [
    "audit ce code", "audite ce code", "analyse ce code", "analyse ton code",
    "analyse le code", "inspecte ton code", "audite ton code",
    "qualite de ton code", "verifie ce code", "vérifie ce code",
    "code audit", "audit python",
]
_CODE_KEYWORDS = [
    "genere un fichier", "genere du code", "ecris un script", "script bash",
    "script python", "ameliore ce code", "revue de code", "corrige ce code",
    "fichier python",
]
_TOOL_CREATION_KEYWORDS = [
    "cree un tool", "crée un tool", "creer un tool", "créer un tool",
    "ajoute un tool", "ajoute un outil", "cree un outil", "crée un outil",
]
_AGENT_LIST_KEYWORDS = [
    "liste les agents", "liste agents", "affiche les agents",
    "affiche moi les agents", "agents disponibles", "quels agents",
]
_AGENT_RUN_KEYWORDS = [
    "lance l agent", "lance l'agent", "lance agent", "execute l agent",
    "execute l'agent", "execute agent", "run agent",
]
_AGENT_ENABLE_KEYWORDS = [
    "active l agent", "active l'agent", "active agent",
    "reactive l agent", "reactive l'agent", "reactive agent",
    "active l'", "active la ",
]
_AGENT_DISABLE_KEYWORDS = [
    "desactive l agent", "desactive l'agent", "desactive agent",
    "stoppe l agent", "stoppe l'agent", "stoppe agent",
    "arrete l agent", "arrete l'agent", "arrete agent",
]
_AGENT_DELETE_KEYWORDS = [
    "supprime l agent", "supprime l'agent", "supprime agent",
    "efface l agent", "efface l'agent", "efface agent",
    "supprime l'", "supprime la ",
]
_PERSONALITY_KEYWORDS = [
    "sois plus sympa", "sois plus gentil", "sois moins froid",
    "change ton ton", "adapte ton style", "parle autrement",
]


def _keyword_fallback_intent(query: str) -> Intent | None:
    """
    Cascade de mots-clés pour les intents sans équivalent dans le schéma
    target/operation. Retourne None si rien ne matche -- dans ce cas,
    IntentRouter.route() retombe sur le classifieur ML.
    """
    q = _normalize(query)

    if q in _GREETING_KEYWORDS:
        return Intent.GREETING
    if q in _THANKS_KEYWORDS:
        return Intent.THANKS
    if q in _GOODBYE_KEYWORDS:
        return Intent.GOODBYE
    if q in _STATUS_SMALLTALK_KEYWORDS:
        return Intent.STATUS_SMALLTALK

    try:
        from core.modules.identity import detect_identity_intent

        if detect_identity_intent(query).get("matched"):
            return Intent.IDENTITY_QUERY
    except Exception:
        if any(k in q for k in _IDENTITY_KEYWORDS):
            return Intent.IDENTITY_QUERY

    if any(k in q for k in _SELF_STATUS_KEYWORDS):
        return Intent.SELF_STATUS
    if any(k in q for k in _TOPOLOGY_KEYWORDS):
        return Intent.TOPOLOGY_SHOW
    if any(k in q for k in _REGISTRY_STATUS_KEYWORDS):
        return Intent.REGISTRY_STATUS
    if any(k in q for k in _REGISTRY_LIST_KEYWORDS):
        return Intent.REGISTRY_LIST
    if any(k in q for k in _NETWORK_KEYWORDS):
        return Intent.NETWORK_STATUS
    if any(k in q for k in _TIME_KEYWORDS):
        return Intent.TIME_QUERY
    if any(k in q for k in _WEATHER_KEYWORDS):
        return Intent.WEATHER_QUERY
    if any(k in q for k in _NEWS_KEYWORDS):
        return Intent.NEWS_QUERY
    if any(k in q for k in _CODE_AUDIT_KEYWORDS):
        return Intent.CODE_AUDIT
    if any(k in q for k in _CODE_KEYWORDS):
        return Intent.CODE
    if any(k in q for k in _TOOL_CREATION_KEYWORDS):
        return Intent.TOOL_CREATION
    if any(k in q for k in _AGENT_LIST_KEYWORDS):
        return Intent.AGENT_LIST
    if any(k in q for k in _AGENT_RUN_KEYWORDS):
        return Intent.AGENT_RUN
    if any(k in q for k in _AGENT_DELETE_KEYWORDS):
        return Intent.AGENT_DELETE
    if any(k in q for k in _AGENT_DISABLE_KEYWORDS):
        return Intent.AGENT_DISABLE
    if any(k in q for k in _AGENT_ENABLE_KEYWORDS):
        return Intent.AGENT_ENABLE
    if any(k in q for k in _PERSONALITY_KEYWORDS):
        return Intent.PERSONALITY_FEEDBACK

    return None


class IntentRouter:
    """
    Routeur d'intentions Néron -- interface publique inchangée (même classe,
    même signature route()) pour compatibilité avec le reste du pipeline.

    Logique interne remplacée (24/07) : classifieur CamemBERT hybride
    (target + règle lexicale/operation) à la place du NLP interne + cascade
    de mots-clés. Validé en holdout honnête à 83.1% Target+Op (vs 65.6% pour
    l'ancien pipeline LLM Ollama), latence ~181ms (vs 25-40s).
    """

    def __init__(self, llm_agent=None) -> None:
        self.llm_agent = llm_agent
        from core.pipeline.intent.neron_intent_classifier import IntentRouter as MLIntentRouter
        self._ml_router = MLIntentRouter()

    async def route(self, query: str) -> IntentResult:
        # Étape 1 : cascade de mots-clés pour les intents sans équivalent
        # dans le schéma target/operation (option 1, 24/07)
        keyword_intent = _keyword_fallback_intent(query)
        if keyword_intent is not None:
            confidence_score = 0.9
            entities: Dict[str, Any] = {"routing_method": "keyword_cascade"}
            logger.info(
                "[NLP] intent=%s method=keyword_cascade", keyword_intent.value
            )
            try:
                from core.modules.self_model import get_self_model

                model = get_self_model()
                model.set_last_intent(str(keyword_intent.value), confidence_score)
            except Exception:
                pass
            return IntentResult(
                intent=keyword_intent,
                confidence="high",
                confidence_score=confidence_score,
                entities=entities,
            )

        # Étape 2 : classifieur ML (target/operation), comme avant
        result = self._ml_router.route(query)
        target = result["target"]
        operation = result["operation"]
        method = result["method"]

        intent = _map_to_intent(target, operation)

        # Le classifieur ne renvoie pas de score de confiance calibré
        # (contrairement à l'ancien pipeline NLP) -- la règle lexicale est
        # déterministe donc traitée comme haute confiance ; le fallback ML
        # comme confiance moyenne par défaut, faute de calibration mesurée.
        confidence_score = 0.95 if method == "lexical_rule" else 0.7
        confidence = (
            "high" if confidence_score >= 0.7
            else ("medium" if confidence_score >= 0.4 else "low")
        )

        entities: Dict[str, Any] = {
            "target": target,
            "operation": operation,
            "routing_method": method,
        }

        # Option 2 (24/07) : quand le classifieur n'identifie vraiment rien
        # (target=unknown), on le signale explicitement via confidence="low"
        # plutôt que de laisser croire à une conversation normale -- ça
        # permet à l'orchestrateur/llm_provider en aval de choisir un repli
        # rapide sans lancer une génération LLM complète si sa logique de
        # routage tient compte de la confidence. ATTENTION : ceci suppose que
        # l'orchestrateur consulte confidence_score pour cette décision --
        # à vérifier côté core/orchestrator avant de considérer résolu le
        # problème des 242s observé sur une requête unknown.
        if target == "unknown" and operation == "unknown":
            confidence_score = 0.1
            confidence = "low"
            entities["genuinely_unknown"] = True

        logger.info(
            "[NLP] intent=%s target=%s operation=%s method=%s",
            intent.value,
            target,
            operation,
            method,
        )

        try:
            from core.modules.self_model import get_self_model

            model = get_self_model()
            model.set_last_intent(str(intent.value), confidence_score)
        except Exception:
            pass

        return IntentResult(
            intent=intent,
            confidence=confidence,
            confidence_score=confidence_score,
            entities=entities,
        )
