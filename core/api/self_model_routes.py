from __future__ import annotations

from fastapi import APIRouter

from modules.self_model.self_model import get_self_model

router = APIRouter(
    prefix="/self-model",
    tags=["self-model"],
)


@router.get("")
async def self_model_state() -> dict:
    sm = get_self_model()
    sm.collect_runtime()
    return sm.to_dict()


@router.get("/summary")
async def self_model_summary() -> dict:
    sm = get_self_model()
    sm.collect_runtime()

    return {
        "summary": sm.summary(),
        "state": sm.to_dict(),
    }
