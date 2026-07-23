from __future__ import annotations

from fastapi import APIRouter

from core.modules.self_model import build_self_model_response, get_self_model
from goal.system.task_manager import get_task_manager
from modules.code_awareness.scanner import scan_project
from core.identity import get_identity

router = APIRouter(
    prefix="/self-model",
    tags=["self-model"],
)


def _snapshot() -> dict:
    model = get_self_model()
    model.refresh()
    return model.to_dict()


@router.get("")
async def self_model_state() -> dict:
    return _snapshot()


@router.get("/summary")
async def self_model_summary() -> dict:
    data = _snapshot()
    return {
        "summary": build_self_model_response("Que sais-tu de toi-même ?"),
        "state": data,
    }


@router.get("/status")
async def self_model_status() -> dict:
    data = _snapshot()
    return {
        "health": data["health"],
        "runtime_mode": data["runtime_mode"],
        "runtime": data["runtime"],
        "diagnostics": data["diagnostics"],
        "recommendations": data["recommendations"],
        "generated_at": data["generated_at"],
    }


@router.get("/context")
async def self_model_context() -> dict:
    data = _snapshot()
    runtime = data.get("runtime", {}) or {}
    task_manager = get_task_manager()

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

    route_task_summary = {
        "total": len(tasks_all),
        "active": len(active_tasks),
        "pending": len(pending_tasks),
        "running": len(running_tasks),
        "failed": len(failed_tasks),
    }
    task_summary = (
        (data.get("tasks") or {}).get("summary")
        or route_task_summary
    )

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
        "memory": data.get("memory", {}),
        "status": data.get("status", {}),
        "health": {
            "realtime": data.get("health_realtime"),
            "historical": data.get("health_historical"),
            "global": data.get("health_global"),
        },
        "goal": data.get("goal", {"active_goal": data.get("active_goal")}),
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
