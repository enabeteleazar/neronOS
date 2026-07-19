"""Core knowledge HTTP routes delegated to the registered provider over A2A."""

from typing import Any

from fastapi import APIRouter, HTTPException

from core.providers.models import ProviderRequest
from core.providers.registry import provider_registry


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


async def _execute(action: str, payload: dict[str, Any]) -> Any:
    providers = provider_registry.by_type("knowledge")
    if not providers:
        raise HTTPException(status_code=503, detail="knowledge provider unavailable")
    response = await provider_registry.execute_via_a2a(
        providers[0].name,
        ProviderRequest(action=action, payload=payload),
    )
    if response.error:
        raise HTTPException(status_code=503, detail=response.error)
    return response.result


@router.get("/query")
async def query(q: str, limit: int = 10) -> Any:
    return await _execute("query", {"query": q, "limit": limit})


@router.get("/documents")
async def documents() -> Any:
    return await _execute("documents", {})
