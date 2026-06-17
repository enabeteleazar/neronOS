from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.api.auth import verify_api_key
from goal.system.task_manager import get_task_manager
from goal.system.task_model import VALID_TASK_PRIORITIES, VALID_TASK_STATUSES

router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(verify_api_key)])


class CreateTaskRequest(BaseModel):
    title: str = Field(..., min_length=1)
    description: str = ""
    priority: str = "normal"
    metadata: dict[str, Any] = {}


class UpdateTaskStatusRequest(BaseModel):
    status: str


def _update_task_status_or_404(task_id: str, status: str) -> dict[str, Any]:
    manager = get_task_manager()

    try:
        task = manager.update_status(task_id, status)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return task


@router.get("/legacy", deprecated=True)
async def list_tasks(
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
) -> dict[str, Any]:
    manager = get_task_manager()

    return {
        "tasks": manager.list_tasks(
            status=status,
            priority=priority,
        )
    }


@router.get("/legacy/status", deprecated=True)
async def task_status() -> dict[str, Any]:
    manager = get_task_manager()

    return manager.get_status_summary()


@router.get("/legacy/running", deprecated=True)
async def running_tasks() -> dict[str, Any]:
    manager = get_task_manager()

    return {
        "tasks": manager.list_running_tasks()
    }


@router.get("/legacy/next", deprecated=True)
async def get_next_task() -> dict[str, Any]:
    manager = get_task_manager()

    return {
        "task": manager.get_next_task()
    }


@router.post("/legacy/next/start", deprecated=True)
async def start_next_task() -> dict[str, Any]:
    manager = get_task_manager()

    task = manager.start_next_task()

    if not task:
        raise HTTPException(status_code=404, detail="No pending task available")

    return {
        "task": task
    }


@router.post("")
async def create_task(payload: CreateTaskRequest) -> dict[str, Any]:
    manager = get_task_manager()

    try:
        task = manager.create_task(
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            metadata=payload.metadata,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    return {
        "task": task
    }


@router.get("/legacy/schema", deprecated=True)
async def task_schema() -> dict[str, Any]:
    return {
        "statuses": sorted(VALID_TASK_STATUSES),
        "priorities": sorted(VALID_TASK_PRIORITIES),
    }


@router.get("/legacy/{task_id}", deprecated=True)
async def get_task(task_id: str) -> dict[str, Any]:
    manager = get_task_manager()

    task = manager.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "task": task
    }


@router.patch("/{task_id}/status")
async def update_task_status(
    task_id: str,
    payload: UpdateTaskStatusRequest,
) -> dict[str, Any]:
    task = _update_task_status_or_404(task_id, payload.status)

    return {
        "task": task
    }


@router.post("/{task_id}/start")
async def start_task(task_id: str) -> dict[str, Any]:
    task = _update_task_status_or_404(task_id, "running")

    return {
        "task": task
    }


@router.post("/{task_id}/complete")
async def complete_task(task_id: str) -> dict[str, Any]:
    task = _update_task_status_or_404(task_id, "done")

    return {
        "task": task
    }


@router.post("/{task_id}/fail")
async def fail_task(task_id: str) -> dict[str, Any]:
    task = _update_task_status_or_404(task_id, "failed")

    return {
        "task": task
    }


@router.post("/legacy/{task_id}/cancel", deprecated=True)
async def cancel_task(task_id: str) -> dict[str, Any]:
    task = _update_task_status_or_404(task_id, "cancelled")

    return {
        "task": task
    }


@router.delete("/{task_id}")
async def delete_task(task_id: str) -> dict[str, Any]:
    manager = get_task_manager()

    deleted = manager.delete_task(task_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "deleted": True,
        "task_id": task_id,
    }


@router.delete("/done/clear")
async def clear_done_tasks() -> dict[str, Any]:
    manager = get_task_manager()

    removed_count = manager.clear_done()

    return {
        "removed": removed_count
    }
