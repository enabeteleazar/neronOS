from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from goal.goals.goal_manager import get_goal_manager
from goal.system.goal_task_bridge import create_task_from_goal

router = APIRouter(prefix="/goals", tags=["goal-tasks"])


@router.post("/active/task")
async def create_task_from_active_goal() -> dict[str, Any]:
    manager = get_goal_manager()
    active_goal = manager.get_active_goal()

    if not active_goal:
        raise HTTPException(status_code=404, detail="No active goal found")

    task = create_task_from_goal(active_goal)

    return {
        "created": True,
        "source": "goal_manager",
        "goal": active_goal,
        "task": task,
    }
