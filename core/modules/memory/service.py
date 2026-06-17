from __future__ import annotations

import re

from .detector import normalize
from .store import save_memory, search_memories


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
    }

    prefixes = [
        "que sais tu sur",
        "que sais tu",
        "tu te souviens de",
        "te rappelles tu de",
    ]

    for prefix in prefixes:
        if value.startswith(prefix):
            query = value.replace(prefix, "", 1).strip()
            return aliases.get(query, query or None)

    return None


def build_memory_response(kind: str, text: str) -> dict:
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
            "memory": saved,
        }

    query = _extract_recall_query(text)
    memories = search_memories(query, limit=10)

    if not memories:
        response = "Je n'ai pas encore de mémoire correspondante."
    else:
        lines = ["Voici ce que j'ai en mémoire :"]
        for m in memories:
            lines.append(f"- [{m['category']}] {m['key']} : {m['value']}")
        response = "\n".join(lines)

    return {
        "response": response,
        "intent": "memory_query",
        "agent": "memory_module",
        "confidence": "high",
        "source": "memory_module",
        "memory_kind": kind,
        "memories": memories,
    }
