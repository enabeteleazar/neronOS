from __future__ import annotations

import importlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.paths import NERON_DATA_DIR
try:
    from goal.goals.goal_manager import get_goal_manager
except ImportError:  # goal absent (service séparé)
    from common.goal_unavailable import unavailable
    get_goal_manager, = unavailable('get_goal_manager')
try:
    from goal.planning import AutonomousPlanner
except ImportError:  # goal absent (service séparé)
    from common.goal_unavailable import unavailable
    AutonomousPlanner, = unavailable('AutonomousPlanner')
try:
    from goal.planning.storage import PlanStorage
except ImportError:  # goal absent (service séparé)
    from common.goal_unavailable import unavailable
    PlanStorage, = unavailable('PlanStorage')
from modules.cognitive.history import append_jsonl

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | neron.cognitive_loop | %(message)s",
)

logger = logging.getLogger("neron.cognitive_loop")

ACTION_HISTORY_PATH = Path(
    os.getenv(
        "NERON_ACTION_HISTORY_PATH",
        str(NERON_DATA_DIR / "action_history.jsonl"),
    )
)


def _json_default(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()

    if hasattr(value, "__dict__"):
        return value.__dict__

    return str(value)


def _save_action(payload: dict[str, Any]) -> None:
    ACTION_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    append_jsonl(ACTION_HISTORY_PATH, payload)


def _read_active_goal() -> str | None:
    goal = get_goal_manager().get_active_goal()
    return str(goal.get("title")) if goal else None


def _recent_plan_exists(goal: str, cooldown_seconds: int = 3600) -> bool:
    storage = PlanStorage()
    now = datetime.now(timezone.utc)

    for plan in storage.history(limit=30):
        if plan.get("source") != "cognitive_loop":
            continue

        if plan.get("goal") != goal:
            continue

        created_at = plan.get("created_at")
        if not created_at:
            return True

        try:
            created = datetime.fromisoformat(created_at)
        except Exception:
            return True

        age = (now - created).total_seconds()
        if age < cooldown_seconds:
            return True

    return False


def _generate_plan_from_goal() -> dict[str, Any]:
    goal = _read_active_goal()

    if not goal:
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "generate_task_plan",
            "target": "planner",
            "priority": "medium",
            "status": "blocked",
            "message": "Aucun objectif actif disponible.",
        }
        _save_action(result)
        return result

    if _recent_plan_exists(goal):
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "generate_task_plan",
            "target": "planner",
            "priority": "low",
            "status": "skipped",
            "message": "Plan récent déjà existant pour cet objectif.",
            "active_goal": goal,
        }
        _save_action(result)
        return result

    planner = AutonomousPlanner()
    storage = PlanStorage()

    plan = planner.create_plan(goal)
    data = plan.to_dict()
    data["approved"] = False
    data["approval_required"] = True
    data["source"] = "cognitive_loop"
    active = get_goal_manager().get_active_goal()
    data["goal_id"] = active.get("id") if active else None

    storage.save(data)

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": "generate_task_plan",
        "target": "planner",
        "priority": "medium",
        "status": "success",
        "message": "Plan généré automatiquement depuis la Cognitive Loop.",
        "generated_plan_id": data.get("id"),
        "generated_plan_goal": data.get("goal"),
    }

    _save_action(result)
    return result


def _run_cognitive_core_once() -> dict[str, Any] | None:
    try:
        module = importlib.import_module("modules.cognitive_core.core")
    except Exception as exc:
        logger.warning("Cognitive Core indisponible: %s", exc)
        return None

    core = None

    if hasattr(module, "get_cognitive_core"):
        try:
            core = module.get_cognitive_core()
        except Exception as exc:
            logger.warning("get_cognitive_core erreur: %s", exc)
            core = None

    if core is None and hasattr(module, "CognitiveCore"):
        try:
            core = module.CognitiveCore()
        except Exception as exc:
            logger.warning("CognitiveCore instanciation erreur: %s", exc)
            core = None

    if core is None:
        return None

    for method_name in ["cycle", "run_cycle", "evaluate", "tick", "step"]:
        method = getattr(core, method_name, None)

        if method is None:
            continue

        try:
            state = method()

            raw_state = _json_default(state)
            state_summary = {
                "timestamp": raw_state.get("timestamp"),
                "self_health": raw_state.get("self_health"),
                "world_status": raw_state.get("world_status"),
                "active_goal": raw_state.get("active_goal"),
                "active_task_count": len(raw_state.get("active_tasks") or []),
                "cognitive_score": raw_state.get("cognitive_score"),
                "next_action": raw_state.get("next_action"),
            } if isinstance(raw_state, dict) else {"value": str(raw_state)[:500]}

            result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": "cognitive_core_cycle",
                "target": "cognitive_core",
                "priority": "medium",
                "status": "success",
                "message": f"Cognitive Core exécuté via {method_name}.",
                "state": state_summary,
            }

            _save_action(result)
            return result

        except Exception as exc:
            logger.warning("Cognitive Core méthode %s erreur: %s", method_name, exc)

    return None


def main() -> None:
    logger.info("CognitiveLoop démarrée")

    while True:
        logger.info("[CognitiveLoop] cycle actif")

        result = _run_cognitive_core_once()

        if result is None:
            result = _generate_plan_from_goal()

        logger.info(
            "[CognitiveLoop] result status=%s action=%s",
            result.get("status"),
            result.get("action"),
        )

        time.sleep(10)


if __name__ == "__main__":
    main()
