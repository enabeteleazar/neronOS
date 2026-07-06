from __future__ import annotations

from fastapi import APIRouter

from core.modules.self_model import get_self_model


router = APIRouter(prefix="/selfmodel", tags=["selfmodel"])


def _snapshot() -> dict:
    model = get_self_model()
    model.refresh()
    return model.to_dict()


@router.get("/status")
async def status() -> dict:
    data = _snapshot()
    return {
        "health": data["health"],
        "runtime_mode": data["runtime_mode"],
        "runtime": data["runtime"],
        "diagnostics": data["diagnostics"],
        "recommendations": data["recommendations"],
        "generated_at": data["generated_at"],
    }


@router.get("/identity")
async def identity() -> dict:
    return _snapshot()["identity"]


@router.get("/capabilities")
async def capabilities() -> dict:
    return _snapshot()["capabilities"]


@router.get("/providers")
async def providers() -> dict:
    return _snapshot()["providers"]


@router.get("/services")
async def services() -> dict:
    return _snapshot()["registered_services"]


@router.get("/agents")
async def agents() -> dict:
    data = _snapshot()
    return {
        **data["agent_topology"],
        "registry": data["agents"],
        "a2a": data["a2a"],
    }


@router.get("/memory")
async def memory() -> dict:
    return _snapshot()["memory"]


@router.get("/goals")
async def goals() -> dict:
    data = _snapshot()
    return {
        "engine": data["goal_engine"],
        "runtime": data["goal"],
        "tasks": data["tasks"],
    }


@router.get("/architecture")
async def architecture() -> dict:
    return _snapshot()["architecture"]
