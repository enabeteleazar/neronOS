"""Core memory HTTP routes delegated to the registered provider over A2A."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.providers.models import ProviderRequest
from core.providers.registry import provider_registry


router = APIRouter(prefix="/memory", tags=["memory"])


class RememberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)
    category: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    category: str | None = None
    limit: int = Field(default=10, ge=1, le=100)


async def _execute(action: str, payload: dict[str, Any]) -> Any:
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
async def memory_status() -> Any:
    return await _execute("status", {})


@router.post("/remember")
async def remember(record: RememberRequest) -> Any:
    return await _execute("remember", record.model_dump(mode="json"))


@router.post("/recall")
async def recall(query: RecallRequest) -> Any:
    return await _execute("recall", query.model_dump(mode="json"))


@router.get("/search")
async def search(q: str) -> Any:
    return await _execute("search", {"query": q})
