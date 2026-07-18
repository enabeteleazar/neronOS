from __future__ import annotations

import importlib
import logging
from typing import Any

from fastapi import APIRouter


logger = logging.getLogger("core.runtime_compat")


def optional_router(module_name: str, *, name: str = "router") -> APIRouter | None:
    try:
        module = importlib.import_module(module_name)
        router = getattr(module, name)
    except Exception as exc:
        logger.warning("Optional router disabled: %s (%s)", module_name, exc)
        return None
    if not isinstance(router, APIRouter):
        logger.warning("Optional router disabled: %s.%s is not an APIRouter", module_name, name)
        return None
    return router


def include_optional_router(app: Any, router: APIRouter | None, *args: Any, **kwargs: Any) -> bool:
    if router is None:
        return False
    app.include_router(router, *args, **kwargs)
    return True


class CapabilityResolver:
    async def get_result(self, request_id: str) -> Any:
        return None

    async def resolve(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "unavailable",
            "reason": "capability resolver is not installed in Core runtime",
        }


class SessionStore:
    pass


class SkillRegistry:
    pass


class _TaskScheduler:
    worker_enabled = False
    max_concurrent_tasks = 0

    def recover_running_tasks(self) -> list[Any]:
        return []

    async def start_worker(self) -> None:
        return None

    async def stop_worker(self) -> None:
        return None

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


_task_scheduler = _TaskScheduler()


def get_task_scheduler() -> _TaskScheduler:
    return _task_scheduler


class _SelfMonitor:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


_self_monitor = _SelfMonitor()


def get_self_monitor() -> _SelfMonitor:
    return _self_monitor
