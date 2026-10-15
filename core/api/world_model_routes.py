from __future__ import annotations

from fastapi import APIRouter

from modules.world_model.world_model import load_world_model_state, get_world_model

router = APIRouter(tags=["world-model"])


@router.get("/world-model/context")
async def world_model_context() -> dict:
    return load_world_model_state()


@router.get("/world-model/status")
async def world_model_status() -> dict:
    data = load_world_model_state()

    return {
        "environment_status": data.get("environment_status"),
        "diagnostics": data.get("diagnostics", []),
        "last_update": data.get("last_update"),
    }


@router.get("/world-model/summary")
async def world_model_summary() -> dict:
    model = get_world_model()
    return {"summary": model.summary()}
