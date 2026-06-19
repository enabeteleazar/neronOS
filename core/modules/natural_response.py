from __future__ import annotations

import asyncio
import json
import re
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 2.5


def _compact_text(value: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
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


def _sentence_count(value: str) -> int:
    return len(re.findall(r"[^.!?]+[.!?]", value))


def _has_first_person(value: str) -> bool:
    return bool(
        re.search(
            r"\bje\b|\bj['’]|\bma\b|\bmon\b|\bmes\b|\bmoi\b",
            value,
            re.IGNORECASE,
        )
    )


def _looks_like_raw_data(value: str) -> bool:
    stripped = value.strip()
    if stripped.startswith(("{", "[")) or stripped.endswith(("}", "]")):
        return True
    if "```" in stripped:
        return True
    if re.search(r"(?:^|\s)/(?:etc|var|home|tmp|usr|opt)/[^\s,.!?;:]+", stripped):
        return True
    return False


def _facts_to_json(facts: dict[str, Any]) -> str:
    try:
        return json.dumps(facts, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return json.dumps({"facts": str(facts)}, ensure_ascii=False)


def _validate_response(
    response: str,
    *,
    max_chars: int,
    max_sentences: int | None,
    require_first_person: bool,
    required_terms: tuple[str, ...] = (),
) -> str | None:
    value = _compact_text(response)
    value = re.sub(r"^Réponse\s*:\s*", "", value, flags=re.IGNORECASE).strip()

    if not value:
        return None
    if len(value) > max_chars:
        return None
    if max_sentences is not None and _sentence_count(value) > max_sentences:
        return None
    if require_first_person and not _has_first_person(value):
        return None
    if _looks_like_raw_data(value):
        return None
    if required_terms and not all(
        term.lower() in value.lower() for term in required_terms
    ):
        return None

    return value


async def try_natural_response(
    *,
    module_name: str,
    question: str,
    facts: dict[str, Any],
    instructions: str,
    max_chars: int,
    max_sentences: int | None = None,
    require_first_person: bool = True,
    required_terms: tuple[str, ...] = (),
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> str | None:
    try:
        from llm.client.client import NéronLLMClient
    except Exception:
        return None

    prompt = (
        f"Module Core : {module_name}\n"
        "Tu reformules uniquement les faits fournis par le Core.\n"
        "Tu ne décides rien, tu ne routes rien, tu ne planifies rien et tu n'inventes aucun fait.\n"
        "Réponds en français, à la première personne lorsque Néron parle de lui-même.\n"
        "Ne renvoie pas de JSON, pas de markdown technique brut, pas de chemins système inutiles.\n"
        f"Contraintes : {instructions}\n\n"
        f"Question utilisateur :\n{question}\n\n"
        f"Faits structurés produits par le Core :\n{_facts_to_json(facts)}\n\n"
        "Réponse naturelle :"
    )

    try:
        client = NéronLLMClient()
        if hasattr(client, "_timeout"):
            client._timeout = min(float(client._timeout), timeout_seconds)
        if hasattr(client, "_retries"):
            client._retries = 0

        result = await asyncio.wait_for(
            client.generate(
                task_type="chat",
                prompt=prompt,
                context={},
                request_id=f"{module_name}-natural-response",
            ),
            timeout=timeout_seconds + 0.5,
        )
    except Exception:
        return None

    if getattr(result, "model_used", "") == "degraded":
        return None

    return _validate_response(
        str(getattr(result, "result", "") or ""),
        max_chars=max_chars,
        max_sentences=max_sentences,
        require_first_person=require_first_person,
        required_terms=required_terms,
    )
