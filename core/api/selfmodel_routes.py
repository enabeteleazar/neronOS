from __future__ import annotations

import asyncio

from fastapi import APIRouter

from core.modules.self_model import get_self_model


router = APIRouter(prefix="/selfmodel", tags=["selfmodel"])


def _snapshot_sync() -> dict:
    model = get_self_model()
    model.refresh()
    return model.to_dict()


async def _snapshot_async() -> dict:
    # Hors de l'event loop : le snapshot appelle systemctl (cf.
    # core/api/self_model_routes.py).
    return await asyncio.to_thread(_snapshot_sync)


@router.get("/status")
async def status() -> dict:
    data = await _snapshot_async()
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
    return (await _snapshot_async())["identity"]


@router.get("/capabilities")
async def capabilities() -> dict:
    return (await _snapshot_async())["capabilities"]


@router.get("/providers")
async def providers() -> dict:
    return (await _snapshot_async())["providers"]


@router.get("/services")
async def services() -> dict:
    return (await _snapshot_async())["registered_services"]


@router.get("/agents")
async def agents() -> dict:
    data = await _snapshot_async()
    return {
        **data["agent_topology"],
        "registry": data["agents"],
        "a2a": data["a2a"],
    }


@router.get("/memory")
async def memory() -> dict:
    return (await _snapshot_async())["memory"]


@router.get("/goals")
async def goals() -> dict:
    data = await _snapshot_async()
    return {
        "engine": data["goal_engine"],
        "runtime": data["goal"],
        "tasks": data["tasks"],
    }


@router.get("/architecture")
async def architecture() -> dict:
    return (await _snapshot_async())["architecture"]
