from __future__ import annotations

from fastapi import APIRouter

from core.modules.self_model import build_self_model_response, get_self_model

router = APIRouter(
    prefix="/self-model",
    tags=["self-model"],
)


@router.get("")
async def self_model_state() -> dict:
    sm = get_self_model()
    sm.refresh()
    return sm.to_dict()


@router.get("/summary")
async def self_model_summary() -> dict:
    sm = get_self_model()
    sm.refresh()

    return {
        "summary": build_self_model_response("Que sais-tu de toi-même ?"),
        "state": sm.to_dict(),
    }
