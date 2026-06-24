from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict

from agents.builtin.base_agent import get_logger

logger = get_logger(__name__)


def _nlp():
    from core.pipeline.nlp.nlp_processor import get_processor
    return get_processor()


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
    PROJECT_STATUS       = "project_status"
    PROJECT_LIST         = "project_list"

    SYSTEM_STATUS        = "system_status"
    NETWORK_STATUS       = "network_status"
    IDENTITY_QUERY       = "identity_query"
    SELF_STATUS          = "self_status"

    NEWS_QUERY           = "news_query"
    WEATHER_QUERY        = "weather_query"
    TODO_ACTION          = "todo_action"
    WIKI_QUERY           = "wiki_query"


_INTENT_MAP: Dict[str, Intent] = {i.value: i for i in Intent}


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


def _normalize(text: str) -> str:
    n = unicodedata.normalize("NFD", text.lower().strip())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")

    for char in ["?", "!", ".", ",", ";", ":"]:
        n = n.replace(char, " ")

    n = n.replace("-", " ")
    n = n.replace("'", " ").replace("’", " ").replace("`", " ")

    return " ".join(n.split())


def _fallback_intent(query: str) -> Intent | None:
    q = _normalize(query)

    greeting_keywords = [
        "salut",
        "salut neron",
        "bonjour",
        "bonjour neron",
        "hello",
        "hello neron",
        "coucou",
        "coucou neron",
        "hey",
        "hey neron",
        "tu es la",
        "tu es la neron",
        "neron tu es la",
    ]


    thanks_keywords = [
        "merci",
        "merci neron",
        "thanks",
        "thank you",
    ]

    goodbye_keywords = [
        "au revoir",
        "bye",
        "a plus",
        "à plus",
        "bonne nuit",
    ]

    status_smalltalk_keywords = [
        "ca va",
        "ça va",
        "tu vas bien",
        "comment vas tu",
        "comment vas-tu",
    ]

    identity_keywords = [
        "qui es tu",
        "qui es-tu",
        "tu es qui",
        "presente toi",
        "présente toi",
        "presente-toi",
        "présente-toi",
        "quel est ton nom",
        "comment tu t appelles",
        "comment tu t'appelles",
        "comment t appelles tu",
        "comment t'appelles tu",
    ]

    self_status_keywords = [
        "etat interne",
        "etat conscience",
        "etat cognitif",
        "self status",
        "self model",
        "selfmodel",
        "que sais tu de toi",
        "que sais-tu de toi",
        "que sais tu de toi meme",
        "que sais-tu de toi-même",
        "tes capacites",
        "tes capacités",
        "capacites de neron",
        "capacités de neron",
    ]

    system_keywords = [
        "statut systeme",
        "etat systeme",
        "status systeme",
        "quel est ton etat actuel",
        "comment va ton systeme",
        "ton systeme fonctionne t il correctement",
        "systeme fonctionne t il correctement",
        "le core fonctionne t il",
        "core fonctionne t il",
        "as tu detecte des problemes",
        "services actifs",
        "quels services sont actifs",
        "liste les services",
        "quels modules sont charges",
        "quels modules sont disponibles",
        "modules charges",
        "modules disponibles",
    ]

    network_keywords = [
        "ports ouverts",
        "etat reseau",
        "status reseau",
    ]

    agent_creation_keywords = [
        "cree un agent",
        "crée un agent",
        "creer un agent",
        "créer un agent",
        "j aimerais un agent",
        "je veux un agent",
        "nouvel agent",
        "genere un agent",
        "génère un agent",
        "ajoute un agent",
    ]

    tool_creation_keywords = [
        "cree un tool",
        "crée un tool",
        "creer un tool",
        "créer un tool",
        "ajoute un tool",
        "ajoute un outil",
        "cree un outil",
        "crée un outil",
        "creer un outil",
        "créer un outil",
    ]

    project_status_keywords = [
        "ou en est mon objectif",
        "où en est mon objectif",
        "etat de mon objectif",
        "état de mon objectif",
        "statut de mon objectif",
        "status de mon objectif",
        "ou en est l objectif",
        "où en est l objectif",
        "ou en est le projet",
        "où en est le projet",
        "il en est ou l agent",
        "il en est où l agent",
        "etat du projet",
        "état du projet",
        "detaille le projet",
        "détaille le projet",
        "statut du projet",
    ]

    project_list_keywords = [
        "liste mes projets",
        "liste les projets",
        "quels agents sont en cours de creation",
        "quels agents sont en cours de création",
        "projets en cours",
        "agents en cours de creation",
        "agents en cours de création",
    ]

    agent_list_keywords = [
        "liste les agents",
        "liste agents",
        "affiche les agents",
        "affiche moi les agents",
        "agents disponibles",
        "quels agents",
        "montre les agents",
        "montre moi les agents",
    ]

    agent_run_keywords = [
        "lance l agent",
        "lance l'agent",
        "lance agent",
        "execute l agent",
        "execute l'agent",
        "execute agent",
        "exécute l agent",
        "exécute l'agent",
        "run agent",
    ]

    agent_promote_keywords = [
        "valide l agent",
        "valide l'agent",
        "valide agent",
        "promeut l agent",
        "promeut l'agent",
        "promeut agent",
        "active l agent",
        "active l'agent",
        "active agent",
    ]

    time_keywords = [
        "quelle heure",
        "heure est il",
        "il est quelle heure",
        "dis moi quelle heure",
    ]

    weather_keywords = [
        "meteo",
        "temperature",
        "temps demain",
        "prevision meteo",
        "previsions meteo",
    ]

    news_keywords = [
        "actualite",
        "actualites",
        "news",
        "infos du jour",
        "information du jour",
    ]

    ha_keywords = [
        "allume",
        "eteins",
        "eteindre",
        "lumiere",
        "lumieres",
        "thermostat",
        "chauffage",
        "prise",
        "volet",
        "home assistant",
    ]

    code_keywords = [
        "genere un fichier",
        "genere du code",
        "ecris un script",
        "script bash",
        "script python",
        "ameliore ce code",
        "revue de code",
        "corrige ce code",
        "fichier python",
    ]

    code_audit_keywords = [
        "audit ce code",
        "audite ce code",
        "analyse ce code",
        "analyse ton code",
        "analyse le code",
        "inspecte ton code",
        "audite ton code",
        "qualite de ton code",
        "verifie ce code",
        "vérifie ce code",
        "relis ce code",
        "revise ce code",
        "révise ce code",
        "controle ce code",
        "contrôle ce code",
        "code audit",
        "audit python",
    ]

    personality_keywords = [
        "sois plus sympa",
        "sois plus gentil",
        "sois moins froid",
        "change ton ton",
        "adapte ton style",
        "parle autrement",
    ]

    if any(k in q for k in time_keywords):
        return Intent.TIME_QUERY

    if q.startswith("/goal ") and any(k in q for k in agent_creation_keywords):
        return Intent.AGENT_CREATION

    if q.startswith("/goal ") and any(k in q for k in tool_creation_keywords):
        return Intent.TOOL_CREATION

    if any(k in q for k in project_list_keywords):
        return Intent.PROJECT_LIST

    if any(k in q for k in project_status_keywords):
        return Intent.PROJECT_STATUS

    if any(k in q for k in agent_creation_keywords):
        return Intent.AGENT_CREATION

    if any(k in q for k in tool_creation_keywords):
        return Intent.TOOL_CREATION

    # Les salutations simples restent conversationnelles pour éviter
    # de détourner les échanges courts comme "bonjour".
    if q in greeting_keywords:
        return Intent.CONVERSATION

    if q in thanks_keywords:
        return Intent.THANKS

    if q in goodbye_keywords:
        return Intent.GOODBYE

    if q in status_smalltalk_keywords:
        return Intent.STATUS_SMALLTALK

    try:
        from core.modules.identity import detect_identity_intent

        if detect_identity_intent(query).get("matched"):
            return Intent.IDENTITY_QUERY
    except Exception:
        if any(k in q for k in identity_keywords):
            return Intent.IDENTITY_QUERY

    if any(k in q for k in self_status_keywords):
        return Intent.SELF_STATUS

    if any(k in q for k in weather_keywords):
        return Intent.WEATHER_QUERY

    if any(k in q for k in news_keywords):
        return Intent.NEWS_QUERY

    if any(k in q for k in ha_keywords):
        return Intent.HA_ACTION

    if any(k in q for k in personality_keywords):
        return Intent.PERSONALITY_FEEDBACK

    if any(k in q for k in code_audit_keywords):
        return Intent.CODE_AUDIT

    if any(k in q for k in code_keywords):
        return Intent.CODE

    if any(k in q for k in system_keywords):
        return Intent.SYSTEM_STATUS

    if any(k in q for k in network_keywords):
        return Intent.NETWORK_STATUS

    if any(k in q for k in agent_list_keywords):
        return Intent.AGENT_LIST

    if any(k in q for k in agent_run_keywords):
        return Intent.AGENT_RUN

    if any(k in q for k in agent_promote_keywords):
        return Intent.AGENT_RUN

    return None


class IntentRouter:
    def __init__(self, llm_agent=None) -> None:
        self.llm_agent = llm_agent

    async def route(self, query: str) -> IntentResult:
        nlp_result = _nlp().process(query)

        intent_str = nlp_result.intent
        intent = _INTENT_MAP.get(intent_str, Intent.CONVERSATION)

        entities = nlp_result.entities
        score = nlp_result.confidence

        fallback = _fallback_intent(query)

        if fallback:
            intent = fallback
            intent_str = fallback.value
            score = max(score, 0.98 if fallback == Intent.GREETING else 0.85)

        confidence = (
            "high"
            if score >= 0.7
            else ("medium" if score >= 0.4 else "low")
        )

        logger.info(
            "[NLP] intent=%s confidence=%.3f entities=%s",
            intent_str,
            score,
            entities,
        )

        try:
            from core.modules.self_model import get_self_model

            model = get_self_model()
            model.set_last_intent(
                str(intent_str),
                score,
            )
        except Exception:
            pass

        return IntentResult(
            intent=intent,
            confidence=confidence,
            confidence_score=score,
            entities=entities,
        )
