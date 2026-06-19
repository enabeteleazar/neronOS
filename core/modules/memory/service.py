from __future__ import annotations

import asyncio
import re
from typing import Any

from .detector import normalize
from .store import save_memory, search_memories
from core.modules.natural_response import try_natural_response


MEMORY_LIMITS = {
    "memory_short": {"max_chars": 360, "max_sentences": 2},
    "memory_default": {"max_chars": 760, "max_sentences": 5},
    "memory_detailed": {"max_chars": 1300, "max_sentences": None},
}


def _extract_memory_text(text: str) -> str:
    value = text.strip()

    patterns = [
        r"(?i)^retiens que\s+",
        r"(?i)^m[ée]morise que\s+",
        r"(?i)^souviens[- ]toi que\s+",
        r"(?i)^note que\s+",
        r"(?i)^garde en m[ée]moire que\s+",
    ]

    for pattern in patterns:
        value = re.sub(pattern, "", value).strip()

    return value


def _guess_category(memory_text: str) -> str:
    value = normalize(memory_text)

    if any(w in value for w in ["mon", "ma", "mes", "moi", "prenom", "nom"]):
        return "user"

    if "neron" in value or "projet" in value:
        return "project"

    return "general"


def _guess_key(memory_text: str) -> str:
    value = normalize(memory_text)

    if "prenom" in value:
        return "prenom"

    if "nom" in value:
        return "nom"

    if "version" in value:
        return "version"

    words = value.split()
    return "_".join(words[:5]) if words else "memoire"


def _extract_recall_query(text: str) -> str | None:
    value = normalize(text)

    aliases = {
        "moi": "user",
        "sur moi": "user",
        "a mon sujet": "user",
        "de moi": "user",
        "neron": "project",
        "projet neron": "project",
        "ta memoire": "memoire neron",
        "de ta memoire": "memoire neron",
        "memoire": "memoire neron",
        "la memoire": "memoire neron",
    }

    prefixes = [
        "comment est organisee",
        "comment est organise",
        "que sais tu sur",
        "que sais tu",
        "tu te souviens de",
        "te rappelles tu de",
        "qu as tu en memoire sur",
        "qu as tu en memoire",
    ]

    for prefix in prefixes:
        if value.startswith(prefix):
            query = value.replace(prefix, "", 1).strip()
            return aliases.get(query, query or None)

    return None


def _response_mode(kind: str, text: str) -> str:
    value = normalize(text)
    if kind == "remember":
        return "memory_short"
    if any(word in value for word in ("detail", "detaille", "organisee", "organise", "architecture")):
        return "memory_detailed"
    if any(word in value for word in ("court", "resume", "simplement")):
        return "memory_short"
    return "memory_default"


def _clean_memory_content(content: str, *, limit: int = 420) -> str:
    value = content or ""
    lines: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line or line == "---":
            continue
        if line.startswith("#"):
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        lines.append(line)

    text = " ".join(lines).strip() or value.strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].strip()
    return text


def _record_to_fact(record: Any, *, backend: str = "legacy", score: float = 1.0) -> dict[str, Any]:
    if isinstance(record, dict):
        content = str(record.get("value") or record.get("content") or "")
        return {
            "category": record.get("category") or "unknown",
            "key": record.get("key"),
            "content": _clean_memory_content(content),
            "source": record.get("source"),
            "backend": backend,
            "score": score,
        }

    memory_record = getattr(record, "record", None)
    if memory_record is None:
        return {"content": _clean_memory_content(str(record)), "backend": backend}

    metadata = getattr(memory_record, "metadata", {}) or {}
    return {
        "category": getattr(memory_record, "category", "unknown"),
        "content": _clean_memory_content(getattr(memory_record, "content", "")),
        "source": getattr(memory_record, "source", None),
        "backend": getattr(record, "backend", backend),
        "score": float(getattr(record, "score", score) or 0.0),
        "path": metadata.get("path") if isinstance(metadata, dict) else None,
    }


def _oblivia_results(query: str | None, *, limit: int = 8) -> list[Any]:
    if not query:
        return []

    try:
        from core.modules.oblivia.manager import ObliviaMemoryManager

        return list(ObliviaMemoryManager().search(query, limit=limit))
    except Exception:
        return []


def _serialize_oblivia_results(results: list[Any]) -> list[dict[str, Any]]:
    serialized = []
    for item in results:
        if hasattr(item, "model_dump"):
            serialized.append(item.model_dump())
        elif hasattr(item, "dict"):
            serialized.append(item.dict())
        else:
            serialized.append({"record": str(item)})
    return serialized


def _memory_facts(
    *,
    kind: str,
    query: str | None,
    legacy_memories: list[dict[str, Any]],
    oblivia_memories: list[Any],
) -> dict[str, Any]:
    facts = [_record_to_fact(memory) for memory in legacy_memories]
    facts.extend(_record_to_fact(memory) for memory in oblivia_memories)
    facts = [fact for fact in facts if fact.get("content")]

    return {
        "kind": kind,
        "query": query,
        "count": len(facts),
        "memories": facts[:8],
        "backends": sorted({str(fact.get("backend")) for fact in facts if fact.get("backend")}),
    }


def _mentions_memory_architecture(facts: dict[str, Any]) -> bool:
    text = " ".join(str(item.get("content") or "") for item in facts.get("memories", []))
    value = normalize(text)
    return "sqlite" in value and "obsidian" in value


def _fallback_recall(facts: dict[str, Any], mode: str) -> str:
    memories = list(facts.get("memories") or [])
    if not memories:
        return "Je n'ai pas encore de souvenir correspondant à cette question."

    if _mentions_memory_architecture(facts):
        if mode == "memory_detailed":
            return (
                "Je me souviens que ma mémoire est organisée autour de deux supports complémentaires. "
                "SQLite porte les données structurées et rapidement interrogeables, tandis qu'Obsidian conserve les connaissances documentaires. "
                "Oblivia réunit ces sources pour retrouver les souvenirs pertinents sans exposer directement les fichiers ou les enregistrements bruts."
            )
        return (
            "Je me souviens que ma mémoire repose sur SQLite pour les données structurées "
            "et Obsidian pour les connaissances documentaires."
        )

    first = str(memories[0].get("content") or "").strip()
    if mode == "memory_short":
        return f"Je me souviens que {first[:240].rstrip('.') }."

    if len(memories) == 1:
        return f"Je me souviens de ceci : {first}"

    snippets = [str(item.get("content") or "").strip().rstrip(".") for item in memories[:3]]
    joined = "; ".join(snippets)
    return f"Je retrouve plusieurs souvenirs pertinents : {joined}."


def _fallback_remember(memory_text: str) -> str:
    return f"C'est mémorisé : {memory_text}"


async def _try_memory_llm(
    *,
    question: str,
    facts: dict[str, Any],
    mode: str,
) -> str | None:
    limits = MEMORY_LIMITS.get(mode, MEMORY_LIMITS["memory_default"])
    instructions = {
        "memory_short": "1 à 2 phrases maximum. Réponds naturellement sans lister les enregistrements.",
        "memory_default": "3 à 5 phrases maximum. Synthétise les souvenirs utiles sans renvoyer de données brutes.",
        "memory_detailed": "Réponse structurée mais courte. Explique l'organisation ou les souvenirs retrouvés sans copier les chemins système.",
    }.get(mode, "Réponse naturelle courte.")

    return await try_natural_response(
        module_name="memory",
        question=question,
        facts=facts,
        instructions=instructions,
        max_chars=int(limits["max_chars"]),
        max_sentences=limits["max_sentences"],
        require_first_person=True,
    )


async def build_memory_response_async(
    kind: str,
    text: str,
    *,
    use_llm: bool = True,
) -> dict[str, Any]:
    mode = _response_mode(kind, text)

    if kind == "remember":
        memory_text = _extract_memory_text(text)

        if not memory_text:
            response = "Je n'ai rien reçu à mémoriser."
            return {
                "response": response,
                "intent": "memory_query",
                "agent": "memory_module",
                "confidence": "medium",
                "source": "memory_module",
                "memory_kind": kind,
                "memory_response_mode": mode,
                "memory_llm_used": False,
            }

        saved = save_memory(
            category=_guess_category(memory_text),
            key=_guess_key(memory_text),
            value=memory_text,
            source="user",
            confidence=1.0,
        )

        try:
            from core.modules.oblivia.manager import ObliviaMemoryManager
            from core.modules.oblivia.schemas import MemoryRecord

            ObliviaMemoryManager().remember(
                MemoryRecord(
                    id=f"legacy-{saved['id']}",
                    source="memory_manager",
                    category=_guess_category(memory_text),
                    content=memory_text,
                )
            )
        except Exception:
            pass

        return {
            "response": _fallback_remember(memory_text),
            "intent": "memory_query",
            "agent": "memory_module",
            "confidence": "high",
            "source": "memory_module",
            "memory_kind": kind,
            "memory_response_mode": mode,
            "memory_llm_used": False,
            "memory": saved,
        }

    query = _extract_recall_query(text)
    legacy_memories = search_memories(query, limit=10)
    oblivia_memories = _oblivia_results(query or normalize(text), limit=8)
    facts = _memory_facts(
        kind=kind,
        query=query,
        legacy_memories=legacy_memories,
        oblivia_memories=oblivia_memories,
    )

    llm_response = None
    if use_llm and facts.get("count"):
        llm_response = await _try_memory_llm(
            question=text,
            facts=facts,
            mode=mode,
        )

    return {
        "response": llm_response or _fallback_recall(facts, mode),
        "intent": "memory_query",
        "agent": "memory_module",
        "confidence": "high",
        "source": "memory_module",
        "memory_kind": kind,
        "memory_response_mode": mode,
        "memory_llm_used": bool(llm_response),
        "memories": legacy_memories,
        "oblivia_memories": _serialize_oblivia_results(oblivia_memories),
    }


def build_memory_response(kind: str, text: str) -> dict:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            build_memory_response_async(
                kind,
                text,
                use_llm=False,
            )
        )

    if kind == "remember":
        memory_text = _extract_memory_text(text)

        if not memory_text:
            response = "Je n'ai rien reçu à mémoriser."
            return {
                "response": response,
                "intent": "memory_query",
                "agent": "memory_module",
                "confidence": "medium",
                "source": "memory_module",
                "memory_kind": kind,
                "memory_response_mode": "memory_short",
                "memory_llm_used": False,
            }

        saved = save_memory(
            category=_guess_category(memory_text),
            key=_guess_key(memory_text),
            value=memory_text,
            source="user",
            confidence=1.0,
        )

        return {
            "response": f"C'est mémorisé : {memory_text}",
            "intent": "memory_query",
            "agent": "memory_module",
            "confidence": "high",
            "source": "memory_module",
            "memory_kind": kind,
            "memory_response_mode": "memory_short",
            "memory_llm_used": False,
            "memory": saved,
        }

    query = _extract_recall_query(text)
    memories = search_memories(query, limit=10)
    oblivia_memories = _oblivia_results(query or normalize(text), limit=8)
    mode = _response_mode(kind, text)
    facts = _memory_facts(
        kind=kind,
        query=query,
        legacy_memories=memories,
        oblivia_memories=oblivia_memories,
    )

    response = _fallback_recall(facts, mode)

    return {
        "response": response,
        "intent": "memory_query",
        "agent": "memory_module",
        "confidence": "high",
        "source": "memory_module",
        "memory_kind": kind,
        "memory_response_mode": mode,
        "memory_llm_used": False,
        "memories": memories,
        "oblivia_memories": _serialize_oblivia_results(oblivia_memories),
    }
