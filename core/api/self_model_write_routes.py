from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.modules.self_model.homelab import set_homelab_slot

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
