"""core/modules/knowledge/service.py

Passerelle entre les intentions "knowledge" détectées et le provider
Obsidian distant. Mirroir de modules/memory/service.py, en plus simple
(lecture seule — pas de remember/forget côté connaissances).
"""
from __future__ import annotations

from typing import Any

from core.providers.models import ProviderRequest
from core.providers.registry import provider_registry

from .detector import extract_knowledge_query


def _result_items(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, dict):
        value = result.get("results") or []
    else:
        value = result
    return value if isinstance(value, list) else []


async def build_knowledge_response_async(kind: str, text: str) -> dict[str, Any]:
    providers = provider_registry.by_type("knowledge")
    provider_info = providers[0] if providers else None
    if provider_info is None:
        return {
            "response": "La base de connaissances n'est pas disponible.",
            "intent": "knowledge_query",
            "agent": "knowledge_provider",
            "confidence": "low",
            "source": "provider_registry",
            "knowledge_kind": kind,
            "error": "knowledge provider unavailable",
        }

    if kind == "documents":
        payload: dict[str, Any] = {}
        action = "documents"
    else:
        action = "query"
        payload = {"query": extract_knowledge_query(text), "limit": 5}

    response = await provider_registry.execute_via_a2a(
        provider_info.name,
        ProviderRequest(action=action, payload=payload),
    )
    result = response.result if isinstance(response.result, dict) else {}
    items = _result_items(response.result)

    if response.error:
        rendered = f"Erreur de la base de connaissances : {response.error}"
    elif kind == "documents":
        docs = result.get("documents") or []
        if not docs:
            rendered = "Je n'ai trouvé aucun document dans la base de connaissances."
        else:
            lines = [f"- {d.get('title') or d.get('path')}" for d in docs[:10]]
            rendered = "\n".join([f"{len(docs)} document(s) trouvé(s) :", *lines])
    elif items:
        lines = [f"- {it.get('title')} : {it.get('snippet')}" for it in items[:3]]
        rendered = "\n".join(["Voici ce que j'ai trouvé :", *lines])
    else:
        rendered = "Je n'ai rien trouvé à ce sujet dans la base de connaissances."

    return {
        "response": rendered,
        "intent": "knowledge_query",
        "agent": provider_info.name,
        "confidence": "high" if not response.error else "low",
        "source": "knowledge_provider:a2a",
        "knowledge_kind": kind,
        "a2a_used": True,
        "knowledge_results": items,
    }
