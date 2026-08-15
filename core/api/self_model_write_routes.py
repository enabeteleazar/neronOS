from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.modules.self_model.homelab import set_homelab_slot
from core.modules.self_model.agents_write import set_agent_status

router = APIRouter(
    prefix="/self-model",
    tags=["self-model-write"],
)


class SetSlotBody(BaseModel):
    catalog_id: str | None = None


@router.post("/homelab/slots/{unit_id}")
async def set_slot(unit_id: str, body: SetSlotBody) -> dict:
    try:
        slots = set_homelab_slot(unit_id, body.catalog_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"slots": slots}


class SetAgentStatusBody(BaseModel):
    enabled: bool


@router.post("/agents/{agent_id}/status")
async def set_agent_status_route(agent_id: str, body: SetAgentStatusBody) -> dict:
    try:
        result = set_agent_status(agent_id, body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return result
