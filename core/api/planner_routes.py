from __future__ import annotations

import asyncio

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from common.paths import NERON_DATA_DIR
from core.api.auth import verify_api_key
from goal.planning import AutonomousPlanner
from goal.planning.executor import PlanExecutor
from goal.planning.storage import PlanStorage
from goal.system.task_manager import get_task_manager
from goal.system.task_executor import get_task_executor
from agents.builtin.communication.telegram_agent import send_notification
from modules.cognitive.critic_engine import get_critic_engine
from goal.goals.goal_orchestrator import get_goal_orchestrator
from goal.goals.goal_manager import get_goal_manager

router = APIRouter(tags=["planner"], dependencies=[Depends(verify_api_key)])

planner = AutonomousPlanner()
storage = PlanStorage()
executor = PlanExecutor()




def _notify_plan_ready(plan: dict) -> None:
    plan_id = str(plan.get("id") or "")
    short_id = plan_id[:8]
    risk = plan.get("risk") or {}

    message = (
        "🧠 Plan prêt à approbation\n\n"
        f"Objectif : {plan.get('goal')}\n"
        f"ID : {short_id}\n"
        f"Risque : {risk.get('risk_level', 'unknown')} ({risk.get('risk_score', '?')}/100)\n\n"
        f"Approuver : /approve {short_id}\n"
        f"Refuser : /refuse {short_id}"
    )

    try:
        asyncio.create_task(send_notification(message, level="info"))
    except RuntimeError:
        pass

def _sync_plan_task_status(plan_id: str) -> None:
    orchestrator = get_goal_orchestrator()
    plan = orchestrator.sync_plan_task_status(plan_id)

    if not plan or plan.get("status") != "tasks_completed":
        return

    if not plan.get("telegram_ready_notified"):
        critic = get_critic_engine()
        risk = plan.get("risk") or critic.evaluate_plan(plan)
        plan["risk"] = risk
        plan["telegram_ready_notified"] = True
        plan["telegram_ready_notified_at"] = datetime.now(timezone.utc).isoformat()
        _notify_plan_ready(plan)
        storage.update(plan)


class PlanRequest(BaseModel):
    goal: str = Field(..., min_length=1)


@router.post("/planner/create")
async def create_plan(payload: PlanRequest) -> dict:
    plan = planner.create_plan(payload.goal)
    data = plan.to_dict()
    data["planner_called"] = True
    data["approved"] = False
    data["approval_required"] = True
    storage.save(data)
    return data


@router.get("/planner/status")
async def planner_status() -> dict:
    return {
        "planner": "available",
        "mode": "approval_required",
        "execution_enabled": True,
        "code_write_mode": "draft_only",
        "source_of_truth": f"{NERON_DATA_DIR / 'neron_state.sqlite3'}:workflows",
        "legacy_mirror": str(NERON_DATA_DIR / "plans.jsonl"),
        "routes": [
            "POST /planner/create",
            "GET /planner/status",
            "GET /planner/history",
            "GET /planner/last",
            "POST /planner/approve/{plan_id}",
            "POST /planner/execute/{plan_id}",
            "POST /planner/execute-approved/{plan_id}",
            "GET /planner/risk/{plan_id}",
            "POST /planner/from-goal",
            "POST /planner/generate-tasks/{plan_id}",
            "POST /planner/sync-tasks",
            "GET /planner/ready",
        ],
    }


@router.get("/planner/history")
async def planner_history(limit: int = 20) -> dict:
    limit = max(1, min(limit, 100))
    plans = storage.history(limit=limit)
    return {
        "count": len(plans),
        "limit": limit,
        "plans": plans,
    }


@router.get("/planner/last")
async def planner_last() -> dict:
    plan = storage.last()
    if not plan:
        raise HTTPException(status_code=404, detail="Aucun plan trouvé.")
    return plan


@router.post("/planner/approve/{plan_id}")
async def approve_plan(plan_id: str) -> dict:
    plan = storage.get(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan introuvable.")

    plan["approved"] = True
    plan["approval_required"] = False
    plan["status"] = "approved"
    plan["error"] = None
    storage.update(plan)
    return plan


@router.post(
    "/planner/execute/{plan_id}",
    deprecated=True,
    description=(
        "Legacy direct execution path. Prefer "
        "POST /planner/execute-approved/{plan_id}."
    ),
)
async def execute_plan(plan_id: str) -> dict:
    plan = storage.get(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan introuvable.")

    critic = get_critic_engine()
    risk = critic.evaluate_plan(plan)

    plan["risk"] = risk
    storage.update(plan)

    if risk.get("execution_allowed") is not True:
        plan["status"] = "blocked_by_risk"
        plan["error"] = "Exécution bloquée par le CriticEngine."
        storage.update(plan)
        return plan

    plan["error"] = None
    result = executor.execute(plan)
    result["risk"] = risk

    if result.get("status") == "done":
        result["status"] = "plan_finished"
        result["error"] = None

    storage.update(result)
    return result


@router.post("/planner/execute-approved/{plan_id}")
async def execute_approved_plan(plan_id: str) -> dict:
    orchestrator = get_goal_orchestrator()
    result = await orchestrator.execute_approved_plan(plan_id, approved_by="api")

    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Plan introuvable.")

    return result


@router.post("/planner/from-goal")
async def planner_from_goal() -> dict:
    active_goal = get_goal_manager().get_active_goal()
    goal_text = active_goal.get("title") if active_goal else None

    if not goal_text:
        raise HTTPException(status_code=404, detail="Aucun objectif actif trouvé.")

    plan = planner.create_plan(str(goal_text))
    data = plan.to_dict()
    data["planner_called"] = True
    data["approved"] = False
    data["approval_required"] = True
    data["goal_id"] = active_goal.get("id")
    data["source"] = "goal_manager"
    storage.save(data)
    return data


@router.get("/planner/risk/{plan_id}")
async def planner_risk(plan_id: str) -> dict:
    plan = storage.get(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan introuvable.")

    critic = get_critic_engine()
    risk = critic.evaluate_plan(plan)

    plan["risk"] = risk
    storage.update(plan)

    return {
        "plan_id": plan_id,
        "goal": plan.get("goal"),
        "risk": risk,
    }


@router.post("/planner/cleanup-duplicates")
async def cleanup_duplicate_plans() -> dict:
    plans = list(reversed(storage.history(limit=1000)))
    seen: set[tuple[str | None, str | None]] = set()
    cleaned = 0

    for plan in reversed(plans):
        key = (plan.get("source"), plan.get("goal"))

        if (
            plan.get("source") == "cognitive_loop"
            and plan.get("status") in {"pending", "approved", "running"}
        ):
            if key in seen:
                plan["status"] = "superseded"
                plan["superseded_reason"] = "Doublon cognitive_loop remplacé par un plan plus récent."
                storage.update(plan)
                cleaned += 1
            else:
                seen.add(key)

    return {
        "status": "success",
        "cleaned": cleaned,
        "message": "Doublons cognitive_loop marqués comme superseded.",
    }


@router.post("/planner/generate-tasks/{plan_id}")
async def generate_tasks_from_plan(plan_id: str) -> dict:
    plan = storage.get(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan introuvable.")

    task_manager = get_task_manager()
    created_tasks = task_manager.create_tasks_from_plan(plan)

    plan["tasks_generated"] = True
    plan["generated_task_ids"] = [
        task.get("id")
        for task in created_tasks
    ]

    storage.update(plan)

    return {
        "status": "success",
        "plan_id": plan_id,
        "created": len(created_tasks),
        "tasks": created_tasks,
    }


@router.post("/tasks/execute-next")
async def execute_next_task() -> dict:
    task_manager = get_task_manager()
    task = task_manager.next_active_task()

    if not task:
        raise HTTPException(status_code=404, detail="Aucune tâche active.")

    executor = get_task_executor()

    task_manager.update_task(
        task["id"],
        {
            "status": "in_progress",
        },
    )

    try:
        result = executor.execute(task)

        if result.get("status") == "success":
            updated = task_manager.update_task(
                task["id"],
                {
                    "status": "completed",
                    "progress": 100,
                    "completed_at": task_manager._now(),
                    "result": result,
                    "error": None,
                },
            )
        elif result.get("status") == "skipped":
            updated = task_manager.update_task(
                task["id"],
                {
                    "status": "skipped",
                    "progress": 100,
                    "result": result,
                },
            )
        else:
            updated = task_manager.fail_task(
                task["id"],
                result.get("error") or result.get("summary") or "Action échouée.",
            )

        if updated and updated.get("plan_id"):
            _sync_plan_task_status(str(updated.get("plan_id")))

        return {
            "status": "success",
            "task": updated,
            "execution": result,
        }

    except Exception as exc:
        failed = task_manager.fail_task(task["id"], str(exc))

        return {
            "status": "failed",
            "task": failed,
            "error": str(exc),
        }


@router.post("/tasks/execute/{task_id}")
async def execute_task(task_id: str) -> dict:
    task_manager = get_task_manager()
    task = task_manager.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Tâche introuvable.")

    executor = get_task_executor()

    task_manager.update_task(
        task_id,
        {
            "status": "in_progress",
        },
    )

    try:
        result = executor.execute(task)

        if result.get("status") == "success":
            updated = task_manager.update_task(
                task_id,
                {
                    "status": "completed",
                    "progress": 100,
                    "completed_at": task_manager._now(),
                    "result": result,
                    "error": None,
                },
            )
        elif result.get("status") == "skipped":
            updated = task_manager.update_task(
                task_id,
                {
                    "status": "skipped",
                    "progress": 100,
                    "result": result,
                },
            )
        else:
            updated = task_manager.fail_task(
                task_id,
                result.get("error") or result.get("summary") or "Action échouée.",
            )

        if updated and updated.get("plan_id"):
            _sync_plan_task_status(str(updated.get("plan_id")))

        return {
            "status": "success",
            "task": updated,
            "execution": result,
        }

    except Exception as exc:
        failed = task_manager.fail_task(task_id, str(exc))

        return {
            "status": "failed",
            "task": failed,
            "error": str(exc),
        }


@router.post("/planner/sync-tasks")
async def sync_all_plan_tasks() -> dict:
    plans = list(reversed(storage.history(limit=1000)))
    synced = 0

    for plan in plans:
        plan_id = plan.get("id")
        if not plan_id:
            continue

        before = plan.get("status")
        _sync_plan_task_status(str(plan_id))

        updated = storage.get(str(plan_id))
        if updated and updated.get("status") != before:
            synced += 1

    return {
        "status": "success",
        "synced": synced,
    }


@router.get("/planner/ready")
async def planner_ready() -> dict:
    ready = [
        plan
        for plan in storage.history(limit=200)
        if plan.get("status") == "approval_required"
        and plan.get("approval_required") is True
        and plan.get("approved") is not True
    ]

    return {
        "count": len(ready),
        "plans": ready,
    }
