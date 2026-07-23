"""Goal engine, task state and registered services snapshot for the Self Model."""

from __future__ import annotations

from typing import Any


def _safe_registered_services() -> dict[str, Any]:
    try:
        from core.infrastructure.registry import service_registry

        services = service_registry.list_services()
        return {
            "count": len(services),
            "services": services,
            "source": "service_registry",
        }
    except Exception as exc:
        return {"count": 0, "services": [], "source": "service_registry", "error": str(exc)}


def _safe_goal_engine() -> dict[str, Any]:
    try:
        from core.goal_engine import goal_engine

        return goal_engine.status()
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}


def _safe_goal_runtime() -> dict[str, Any]:
    goal: dict[str, Any] | None = None
    runtime_status: dict[str, Any] | None = None

    try:
        from goal.goals.goal_manager import get_goal_manager

        goal = get_goal_manager().get_active_goal()
    except Exception:
        goal = None

    goal_id = None
    if isinstance(goal, dict):
        goal_id = goal.get("id") or goal.get("goal_id")

    if goal_id:
        try:
            from goal.goals.execution_engine import get_goal_execution_engine

            runtime_status = get_goal_execution_engine().get_goal_status(str(goal_id))
        except Exception as exc:
            runtime_status = {"error": str(exc)}

    return {
        "active_goal": goal,
        "runtime_status": runtime_status,
    }


def _safe_task_state() -> dict[str, Any]:
    try:
        from goal.system.task_manager import get_task_manager

        tasks = get_task_manager().list_tasks()
    except Exception as exc:
        return {
            "summary": {
                "total": 0,
                "active": 0,
                "pending": 0,
                "running": 0,
                "failed": 0,
            },
            "error": str(exc),
        }

    statuses = [
        str(task.get("status") or "unknown").lower()
        for task in tasks
        if isinstance(task, dict)
    ]
    return {
        "summary": {
            "total": len(statuses),
            "active": sum(
                status in {"pending", "active", "todo", "in_progress", "running"}
                for status in statuses
            ),
            "pending": sum(
                status in {"pending", "todo", "queued"}
                for status in statuses
            ),
            "running": sum(
                status in {"running", "in_progress"}
                for status in statuses
            ),
            "failed": sum(
                status in {"failed", "error"}
                for status in statuses
            ),
        }
    }
