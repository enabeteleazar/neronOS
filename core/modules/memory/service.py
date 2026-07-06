"""Compatibility gateway from Core memory intents to Oblivia.

No memory is stored or interpreted here. The registered memory provider owns
understanding, persistence, recall and natural knowledge answers.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from core.providers.models import ProviderRequest
from core.providers.registry import provider_registry

from .detector import normalize


def _remember_content(text: str) -> str:
    value = text.strip()
    for pattern in (
        r"(?i)^retiens que\s+",
        r"(?i)^m[ée]morise que\s+",
        r"(?i)^souviens[- ]toi que\s+",
        r"(?i)^note que\s+",
        r"(?i)^garde en m[ée]moire que\s+",
    ):
        value = re.sub(pattern, "", value).strip()
    return value.rstrip(" .")


def _result_items(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, dict):
        value = result.get("results") or []
    else:
        value = result
    return value if isinstance(value, list) else []


async def build_memory_response_async(
    kind: str,
    text: str,
    *,
    use_llm: bool = True,
) -> dict[str, Any]:
    del use_llm  # Memory answers belong to Oblivia, never to the Core LLM path.
    providers = provider_registry.by_type("memory")
    provider_info = providers[0] if providers else None
    if provider_info is None:
        return {
            "response": "Le provider mémoire n'est pas disponible.",
            "intent": "memory_query",
            "agent": "memory_provider",
            "confidence": "low",
            "source": "provider_registry",
            "memory_kind": kind,
            "memory_llm_used": False,
            "error": "memory provider unavailable",
        }

    if kind in {"remember", "update"}:
        content = _remember_content(text)
        payload = {
            "content": content,
            "category": "unknown",
            "metadata": {"source": "core_memory_gateway"},
        }
    else:
        content = ""
        payload = {"query": normalize(text), "limit": 10}

    response = await provider_registry.execute_via_a2a(
        provider_info.name,
        ProviderRequest(action=kind, payload=payload),
    )
    result = response.result if isinstance(response.result, dict) else {}
    items = _result_items(response.result)
    answer = result.get("answer")

    if response.error:
        rendered = f"Erreur du provider mémoire : {response.error}"
    elif kind in {"remember", "update"}:
        provider_metadata = result.get("metadata") or {}
        rendered = str(
            provider_metadata.get("natural_response")
            or f"C’est mémorisé : {content}"
        )
    elif kind == "forget":
        rendered = (
            "C’est oublié."
            if int(result.get("forgotten") or 0)
            else "Je n’ai trouvé aucune connaissance à oublier."
        )
    elif answer:
        rendered = str(answer)
    elif items:
        rendered = "Je retrouve ceci : " + "; ".join(
            str((item.get("record") or {}).get("content") or "")
            for item in items[:3]
        )
    else:
        rendered = "Je n'ai pas encore de souvenir correspondant à cette question."

    return {
        "response": rendered,
        "intent": "memory_query",
        "agent": provider_info.name,
        "confidence": "high" if not response.error else "low",
        "source": "memory_provider:a2a",
        "memory_kind": kind,
        "memory_response_mode": "provider",
        "memory_llm_used": False,
        "a2a_used": True,
        "memory": response.result if kind in {"remember", "update"} else None,
        "memories": items,
        "knowledge_facts": result.get("facts") or [],
    }


def build_memory_response(kind: str, text: str) -> dict[str, Any]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(build_memory_response_async(kind, text))
    raise RuntimeError(
        "build_memory_response cannot run inside an event loop; "
        "use build_memory_response_async"
    )
