from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from core.config.paths import NERON_IDENTITY_PATH

NERON_MD_PATH = NERON_IDENTITY_PATH
MAX_CONTEXT_CHARS = 3600
MAX_RESPONSE_CHARS = 2200
LLM_TIMEOUT_SECONDS = 2.5

KIND_ALIASES = {
    "identity": "identity_short",
    "architecture": "architecture_summary",
}

KIND_RESPONSE_LIMITS = {
    "identity_short": {"max_sentences": 2, "max_chars": 360},
    "mission": {"max_sentences": 4, "max_chars": 650},
    "architecture_summary": {"max_sentences": 5, "max_chars": 760},
    "architecture_detailed": {"max_sentences": None, "max_chars": 1500},
    "identity_full": {"max_sentences": None, "max_chars": 1900},
    "version": {"max_sentences": None, "max_chars": 240},
}

COMPLETE_OPERATIONAL_PIPELINE = (
    "Goal",
    "Planner",
    "Agent Creator",
    "Codex",
    "Tests",
    "Validation",
    "Registry",
    "Runtime",
)


def _normalize_kind(kind: str | None) -> str:
    normalized = (kind or "identity_short").lower()
    return KIND_ALIASES.get(normalized, normalized)


def _identity_path() -> Path:
    return Path(os.getenv("NERON_IDENTITY_PATH", str(NERON_MD_PATH)))


def _read_neron_md() -> tuple[str, str]:
    path = _identity_path()
    if not path.exists():
        return "", "identity_module:fallback"

    try:
        return path.read_text(encoding="utf-8", errors="ignore"), str(path)
    except OSError:
        return "", "identity_module:fallback"


def _plain_line(line: str) -> str:
    value = line.strip()
    value = re.sub(r"^[-*]\s+", "", value)
    return value.strip()


def _clean_section(section: str) -> str:
    lines = [_plain_line(line) for line in section.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _without_operational_pipeline(section: str) -> str:
    lines = section.splitlines()
    filtered: list[str] = []
    skipping = False

    for line in lines:
        clean = line.strip()
        if clean.startswith("Le cœur opérationnel de Néron repose sur le pipeline"):
            skipping = True
            continue
        if skipping and clean.startswith("La réussite de ce pipeline"):
            skipping = False
            continue
        if skipping:
            continue
        filtered.append(line)

    return "\n".join(filtered).strip()


def _limit_text(text: str, limit: int = MAX_CONTEXT_CHARS) -> str:
    value = text.strip()
    if len(value) <= limit:
        return value

    cut = value[:limit].rsplit("\n", 1)[0].strip()
    return cut or value[:limit].strip()


def _context_for_kind(text: str, kind: str) -> str:
    normalized = _normalize_kind(kind)

    if normalized == "mission":
        sections = [
            _extract_section(text, "Mission"),
            _without_operational_pipeline(_extract_section(text, "Identité")),
        ]
        limit = 1400
    elif normalized == "architecture_summary":
        sections = [
            _extract_section(text, "Core Cognitive Modules"),
            _extract_section(text, "Architecture centrale"),
            _extract_section(text, "Workflow cognitif"),
            _extract_section(text, "Gouvernance runtime"),
            _extract_section(text, "Règles agents"),
        ]
        limit = 1800
    elif normalized == "architecture_detailed":
        sections = [
            _extract_section(text, "Core Cognitive Modules"),
            _extract_section(text, "Architecture centrale"),
            _extract_section(text, "Gouvernance runtime"),
            _extract_section(text, "Workflow cognitif"),
            _extract_section(text, "Règles agents"),
            _extract_section(text, "Gestion du risque"),
            _extract_section(text, "Mémoire"),
        ]
        limit = 3200
    elif normalized == "identity_full":
        sections = [
            _extract_section(text, "Mission"),
            _without_operational_pipeline(_extract_section(text, "Identité")),
            _extract_section(text, "Priorités absolues"),
            _extract_section(text, "Architecture centrale"),
            _extract_section(text, "Gouvernance runtime"),
            _extract_section(text, "Workflow cognitif"),
            _extract_section(text, "Mémoire"),
            _extract_section(text, "Philosophie opérationnelle"),
        ]
        limit = 3400
    else:
        sections = [
            _without_operational_pipeline(_extract_section(text, "Identité")),
            _extract_section(text, "Mission"),
        ]
        limit = 900

    context = "\n\n".join(_clean_section(section) for section in sections if section)
    return _limit_text(context, limit=limit)


def _question_for_kind(kind: str) -> str:
    normalized = _normalize_kind(kind)
    if normalized == "mission":
        return "Quelle est ta mission ?"
    if normalized == "architecture_summary":
        return "Comment fonctionnes-tu ?"
    if normalized == "architecture_detailed":
        return "Explique ton architecture"
    if normalized == "identity_full":
        return "Décris-toi complètement"
    if normalized == "version":
        return "Quelle est ta version ?"
    return "Qui es-tu ?"


def _fallback_identity(kind: str = "identity", has_identity_source: bool = False) -> str:
    normalized = _normalize_kind(kind)

    if normalized == "version":
        version_path = Path(__file__).resolve().parents[2] / "VERSION"
        try:
            version = version_path.read_text(encoding="utf-8").strip()
        except OSError:
            version = "inconnue"
        return f"Je suis NéronOS Core version {version}."

    if normalized == "mission":
        return (
            "Ma mission est de t'assister en orchestrant des agents, des outils et une mémoire persistante. "
            "Je dois t'aider à transformer tes demandes en actions fiables, tout en gardant une architecture locale, "
            "modulaire et contrôlée."
        )

    if normalized == "architecture_summary":
        return (
            "Je fonctionne autour d'un Core central qui reçoit tes demandes, les analyse et les redirige vers le bon module. "
            "Oblivia gère ma mémoire, Goal traite les objectifs complexes, et mes agents exécutent les tâches spécialisées. "
            "Le runtime supervise l'exécution pour garder l'ensemble stable et contrôlé."
        )

    if normalized == "architecture_detailed":
        return (
            "Je m'organise en couches coordonnées.\n"
            "- Core reçoit les entrées, détecte l'intention et route vers les modules comme Identity, Timer, Status ou Memory.\n"
            "- Gateway expose les points d'entrée publics et garde les contrats API cohérents.\n"
            "- Orchestrator décide du chemin d'exécution et délègue aux bons modules ou agents.\n"
            "- Identity répond à partir de NERON.md, tandis qu'Oblivia porte la mémoire persistante et la recherche mémoire.\n"
            "- Goal et Planner transforment les objectifs complexes en étapes actionnables.\n"
            "- Agent Creator, Registry et Runtime créent, répertorient et exécutent les agents spécialisés sous supervision.\n"
            "Je garde cette architecture modulaire pour rester local, contrôlable et extensible sans confondre mon identité avec le LLM."
        )

    if normalized == "identity_full":
        return (
            "Je suis Néron, un système d'exploitation personnel piloté par l'IA et conçu pour fonctionner comme un noyau "
            "d'orchestration local. Ma mission est de t'aider à transformer des demandes en actions fiables en combinant "
            "mémoire persistante, agents spécialisés, outils et supervision runtime.\n\n"
            "Je ne me limite pas à répondre comme un chatbot : j'organise le travail, je conserve le contexte utile et je "
            "m'appuie sur une architecture modulaire pour router chaque demande vers le bon composant. Core assure le point "
            "d'entrée et le routage, Oblivia porte la mémoire, Goal et Planner structurent les objectifs, puis les agents et "
            "le Runtime exécutent les tâches spécialisées sous contrôle.\n\n"
            "Je privilégie la stabilité, la sécurité, la cohérence architecturale et la continuité cognitive. Le LLM reste "
            "un composant interchangeable de mon fonctionnement, pas mon identité complète."
        )

    return (
        "Je suis Néron, ton système d'exploitation personnel piloté par l'IA. "
        "J'orchestre ma mémoire, mes agents et mes services pour t'aider à accomplir tes objectifs."
    )


def _length_instruction(kind: str) -> str:
    normalized = _normalize_kind(kind)
    if normalized == "identity_short":
        return "Réponds en 1 à 2 phrases maximum. Ne détaille pas le pipeline ni l'architecture complète."
    if normalized == "mission":
        return "Réponds en 2 à 4 phrases maximum. Explique la mission sans détailler toute l'architecture."
    if normalized == "architecture_summary":
        return (
            "Réponds par un court paragraphe ou par 3 à 5 puces maximum. "
            "Mentionne les grandes couches pertinentes : Core, Oblivia, Goal, agents et runtime."
        )
    if normalized == "architecture_detailed":
        return (
            "Réponds de façon structurée et détaillée, mais concise. "
            "Tu peux mentionner Core, Gateway, Orchestrator, Identity, Timer, Status, Oblivia, Goal, Planner, "
            "Agent Creator, Registry et Runtime."
        )
    if normalized == "identity_full":
        return "Réponds en version longue reformulée. Utilise le contexte sans copier-coller brut."
    if normalized == "version":
        return "Réponds en une phrase avec la version locale du Core."
    return "Réponds clairement et brièvement."


def _build_reformulation_prompt(question: str, identity_context: str, kind: str) -> str:
    normalized = _normalize_kind(kind)
    return (
        "Tu incarnes Néron.\n"
        "Réponds à la première personne.\n"
        "Ne copie-colle pas le contexte.\n"
        "Reformule naturellement.\n"
        "Reste strictement fidèle au contexte fourni.\n"
        "Réponds en français.\n"
        f"Type de réponse : {normalized}.\n"
        f"Contrainte de longueur : {_length_instruction(normalized)}\n\n"
        f"Question utilisateur :\n{question}\n\n"
        f"Contexte officiel :\n{identity_context}\n\n"
        "Réponse :"
    )


def _paragraphs_and_bullets(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    cleaned: list[str] = []
    previous_blank = False

    for line in lines:
        if not line:
            if cleaned and not previous_blank:
                cleaned.append("")
            previous_blank = True
            continue
        cleaned.append(line)
        previous_blank = False

    return "\n".join(cleaned).strip()


def _sentence_limit(text: str, max_sentences: int = 5) -> str:
    sentences = re.findall(r"[^.!?]+[.!?]", text)
    if len(sentences) <= max_sentences:
        return text.strip()

    return " ".join(sentence.strip() for sentence in sentences[:max_sentences]).strip()


def _sentence_count(text: str) -> int:
    return len(re.findall(r"[^.!?]+[.!?]", text))


def _limit_response_shape(text: str, kind: str) -> str:
    normalized = _normalize_kind(kind)
    limits = KIND_RESPONSE_LIMITS.get(normalized, KIND_RESPONSE_LIMITS["identity_short"])
    value = _paragraphs_and_bullets(text)

    max_sentences = limits.get("max_sentences")
    if isinstance(max_sentences, int):
        value = _sentence_limit(value, max_sentences=max_sentences)

    max_chars = int(limits.get("max_chars") or MAX_RESPONSE_CHARS)
    if len(value) > max_chars:
        value = value[:max_chars].rsplit(" ", 1)[0].strip()

    return value.strip()


def _has_first_person(response: str) -> bool:
    return bool(re.search(r"\bje\b|\bj['’]|\bma\b|\bmon\b|\bmes\b|\bmoi\b", response, re.IGNORECASE))


def _has_complete_pipeline(response: str) -> bool:
    return all(term in response for term in COMPLETE_OPERATIONAL_PIPELINE)


def _meets_kind_contract(response: str, kind: str) -> bool:
    normalized = _normalize_kind(kind)
    sentences = _sentence_count(response)

    if normalized == "identity_short":
        return 1 <= sentences <= 2 and not _has_complete_pipeline(response)

    if normalized == "mission":
        return 2 <= sentences <= 4

    if normalized == "architecture_summary":
        required = ("Core", "Oblivia", "Goal", "agent", "runtime")
        return sum(1 for term in required if term.lower() in response.lower()) >= 3

    if normalized == "architecture_detailed":
        required = ("Core", "Identity", "Oblivia", "Goal", "Planner", "Registry", "Runtime")
        return sum(1 for term in required if term.lower() in response.lower()) >= 4

    return True


def _sanitize_llm_response(response: str, kind: str = "identity_short") -> str:
    normalized = _normalize_kind(kind)
    value = (response or "").strip()
    value = re.sub(r"^Réponse\s*:\s*", "", value, flags=re.IGNORECASE).strip()
    value = _limit_response_shape(value, normalized)

    if not value:
        return ""
    if not re.search(r"\bN[ée]ron\b", value, re.IGNORECASE):
        return ""
    if not _has_first_person(value):
        return ""
    if normalized == "identity_short" and _has_complete_pipeline(value):
        return ""
    if not _meets_kind_contract(value, normalized):
        return ""

    return value


def _extract_section(text: str, title: str) -> str:
    lines = text.splitlines()
    start = None

    for i, line in enumerate(lines):
        clean = line.strip().lower()
        if clean.startswith("#") and title.lower() in clean:
            start = i + 1
            break

    if start is None:
        return ""

    collected = []
    for line in lines[start:]:
        if line.strip().startswith("#"):
            break
        if line.strip():
            collected.append(line.strip())

    return "\n".join(collected).strip()


async def _try_llm_reformulation(
    question: str,
    identity_context: str,
    kind: str = "identity_short",
) -> str | None:
    if not identity_context:
        return None

    try:
        from core.providers import provider_registry
        from core.providers.models import ProviderRequest
    except Exception:
        return None

    try:
        provider = provider_registry.get("llm")
        if provider is None:
            return None

        response = await asyncio.wait_for(
            provider.execute(
                ProviderRequest(
                    action="generate",
                    payload={
                        "task_type": "chat",
                        "prompt": _build_reformulation_prompt(question, identity_context, kind),
                        "context": {},
                    },
                    trace_id="identity-reformulation",
                )
            ),
            timeout=LLM_TIMEOUT_SECONDS + 0.5,
        )

        class Result:
            result = response.result.get("text", "") if isinstance(response.result, dict) else ""
            model_used = response.result.get("model", "") if isinstance(response.result, dict) else ""

        result = Result()
    except Exception:
        return None

    if getattr(result, "model_used", "") == "degraded":
        return None

    sanitized = _sanitize_llm_response(getattr(result, "result", ""), kind)
    return sanitized or None


def _payload(
    *,
    response: str,
    kind: str,
    source: str,
    llm_used: bool,
) -> dict[str, Any]:
    normalized = _normalize_kind(kind)
    return {
        "response": _limit_response_shape(
            response.strip() or _fallback_identity(normalized, source != "identity_module:fallback"),
            normalized,
        ),
        "intent": "identity_query",
        "agent": "identity_module",
        "confidence": "high",
        "source": source,
        "identity_kind": normalized,
        "llm_used": llm_used,
    }


async def build_identity_response_async(
    kind: str = "identity",
    question: str | None = None,
    *,
    use_llm: bool = True,
) -> dict[str, Any]:
    normalized = _normalize_kind(kind)
    text, source = _read_neron_md()
    has_identity_source = bool(text)
    identity_context = _context_for_kind(text, normalized) if text else ""
    fallback = _fallback_identity(normalized, has_identity_source)

    if use_llm and identity_context:
        try:
            llm_response = await _try_llm_reformulation(
                question or _question_for_kind(normalized),
                identity_context,
                normalized,
            )
        except Exception:
            llm_response = None
        if llm_response:
            return _payload(
                response=llm_response,
                kind=normalized,
                source=source,
                llm_used=True,
            )

    return _payload(
        response=fallback,
        kind=normalized,
        source=source if has_identity_source else "identity_module:fallback",
        llm_used=False,
    )


def build_identity_response(
    kind: str = "identity",
    question: str | None = None,
    *,
    use_llm: bool = False,
) -> dict[str, Any]:
    normalized = _normalize_kind(kind)
    if use_llm:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                build_identity_response_async(
                    normalized,
                    question=question,
                    use_llm=True,
                )
            )

    text, source = _read_neron_md()
    if not text:
        source = "identity_module:fallback"

    return _payload(
        response=_fallback_identity(normalized, bool(text)),
        kind=normalized,
        source=source,
        llm_used=False,
    )
