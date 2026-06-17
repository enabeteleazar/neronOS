from __future__ import annotations

from fastapi import APIRouter

from modules.self_model.self_model import get_self_model
from goal.system.task_manager import get_task_manager
from modules.code_awareness.scanner import scan_project
from core.identity import get_identity

router = APIRouter(tags=["self-model-context"])


@router.get("/self-model/status")
async def self_model_status() -> dict:
    model = get_self_model()
    model.collect_runtime()
    data = model.to_dict()

    return {
        "health": data.get("health"),
        "runtime_mode": data.get("runtime_mode"),
        "last_update": data.get("last_update"),
        "diagnostics": data.get("diagnostics", []),
    }


@router.get("/self-model/context")
async def self_model_context() -> dict:
    model = get_self_model()
    task_manager = get_task_manager()

    model.refresh()

    data = model.to_dict()
    runtime = data.get("runtime", {}) or {}

    try:
        tasks_all = task_manager.list_tasks()
    except Exception:
        tasks_all = []

    try:
        active_tasks = task_manager.list_active_tasks()
    except Exception:
        try:
            active_tasks = task_manager.get_active_tasks()
        except Exception:
            active_tasks = []

    pending_tasks = [
        task for task in tasks_all
        if task.get("status") in {"pending", "todo", "queued"}
    ]

    failed_tasks = [
        task for task in tasks_all
        if task.get("status") in {"failed", "error"}
    ]

    running_tasks = [
        task for task in tasks_all
        if task.get("status") in {"running", "in_progress"}
    ]

    next_task = pending_tasks[0] if pending_tasks else None

    task_summary = {
        "total": len(tasks_all),
        "active": len(active_tasks),
        "pending": len(pending_tasks),
        "running": len(running_tasks),
        "failed": len(failed_tasks),
    }

    try:
        code_scan = scan_project(max_depth=1)
        code_awareness = {
            "modules": code_scan.get("modules", 0),
            "files": code_scan.get("files", 0),
            "last_scan": None,
            "architecture_known": True,
        }
    except Exception:
        code_awareness = {
            "modules": 0,
            "files": 0,
            "last_scan": None,
            "architecture_known": False,
        }

    return {
        "identity": get_identity(),
        "health": {
            "realtime": data.get("health_realtime"),
            "historical": data.get("health_historical"),
            "global": data.get("health_global"),
        },
        "goal": data.get("active_goal"),
        "tasks": {
            "summary": task_summary,
            "next": next_task,
            "running": running_tasks,
        },
        "diagnostics": data.get("diagnostics", []),
        "recommendations": data.get("recommendations", []),
        "summary": data.get("cognitive_summary"),
        "runtime": runtime,
        "runtime_trend": data.get("runtime_trend", {}),
        "long_term_state_memory": data.get("long_term_state_memory", {}),
        "self_confidence": data.get("self_confidence", {}),
        "capabilities": data.get("capabilities", {}),
        "performance_self_evaluation": data.get("performance_self_evaluation", {}),
        "services": data.get("services", {}),
        "code_awareness": code_awareness,
        "cognitive_state": data.get("cognitive_state", {}),
        "last_activity": {
            "last_event": data.get("last_event"),
            "last_intent": data.get("last_intent"),
            "last_agent": data.get("last_agent"),
        },
    }
