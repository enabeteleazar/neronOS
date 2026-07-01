"""Legacy `/memory/*` API routed to the registered provider over A2A."""

from fastapi import APIRouter, HTTPException

from core.providers.models import ProviderRequest
from core.providers.registry import provider_registry
from memory.oblivia.schemas import MemoryQuery, MemoryRecord


router = APIRouter(prefix="/memory", tags=["memory"])


async def _execute(action: str, payload: dict):
    providers = provider_registry.by_type("memory")
    if not providers:
        raise HTTPException(status_code=503, detail="memory provider unavailable")
    response = await provider_registry.execute_via_a2a(
        providers[0].name,
        ProviderRequest(action=action, payload=payload),
    )
    if response.error:
        raise HTTPException(status_code=503, detail=response.error)
    return response.result


@router.get("/status")
async def memory_status():
    return await _execute("status", {})


@router.post("/remember")
async def remember(record: MemoryRecord):
    return await _execute("remember", record.model_dump(mode="json"))


@router.post("/recall")
async def recall(query: MemoryQuery):
    return await _execute("recall", query.model_dump(mode="json"))


@router.get("/search")
async def search(q: str):
    return await _execute("search", {"query": q})
