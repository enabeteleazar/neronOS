from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from common.paths import NERON_DATA_DIR
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
try:
    from goal.system.task_manager import get_task_manager
except ImportError:  # goal absent (service séparé)
    from common.goal_unavailable import unavailable
    get_task_manager, = unavailable('get_task_manager')
from modules.cognitive.history import append_jsonl


ACTION_HISTORY_PATH = Path(
    os.getenv(
        "NERON_ACTION_HISTORY_PATH",
        str(NERON_DATA_DIR / "action_history.jsonl"),
    )
)


class ActionExecutor:
    """
    ActionExecutor minimal de Néron.

    Transforme une décision cognitive en résultat d'exécution.
    Version prudente : aucune modification système réelle.
    """

    def execute(
        self,
        decision: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        action = decision.get("action")
        target = decision.get("target")
        priority = decision.get("priority", "medium")

        runtime_policy = (context or {}).get("runtime_policy", {}) or {}
        runtime_mode = runtime_policy.get("runtime_mode", "normal")
        autonomous_actions_allowed = runtime_policy.get(
            "autonomous_actions_allowed",
            True,
        )
        heavy_reasoning_allowed = runtime_policy.get(
            "heavy_reasoning_allowed",
            True,
        )

        critical_actions = {
            "continue_monitoring",
            "analyze_system_resources",
        }

        heavy_actions = {
            "generate_task_plan",
            "analyze_world_state",
        }

        if not autonomous_actions_allowed and action not in critical_actions:
            result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": action,
                "target": target,
                "priority": priority,
                "status": "blocked",
                "message": "Action bloquée par RuntimeGovernor : actions autonomes désactivées.",
                "runtime_mode": runtime_mode,
                "runtime_policy": runtime_policy,
            }

            self._save_execution(result)
            return result

        if not heavy_reasoning_allowed and action in heavy_actions:
            result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": action,
                "target": target,
                "priority": priority,
                "status": "blocked",
                "message": "Action bloquée par RuntimeGovernor : raisonnement lourd désactivé.",
                "runtime_mode": runtime_mode,
                "runtime_policy": runtime_policy,
            }

            self._save_execution(result)
            return result

        status = "noop"
        message = "Aucune action exécutée."

        if action == "analyze_system_resources":
            status = "success"
            message = "Analyse des ressources système demandée via SelfModel."

        elif action == "analyze_world_state":
            status = "success"
            message = "Analyse de l'état du monde demandée via WorldModel."

        elif action == "restore_active_goal":
            status = "success"
            message = "Restauration de l'objectif actif demandée via GoalManager."

        elif action == "generate_task_plan":
            active_goal = (context or {}).get("active_goal")

            if not active_goal:
                status = "blocked"
                message = "Aucun objectif actif disponible pour générer un plan."
            else:
                planner = AutonomousPlanner()
                storage = PlanStorage()

                recent_exists = False
                for existing_plan in storage.history(limit=50):
                    if (
                        existing_plan.get("source") == "cognitive_loop"
                        and existing_plan.get("goal") == str(active_goal)
                        and existing_plan.get("status") in {"pending", "approved", "running"}
                    ):
                        recent_exists = True
                        plan_data = existing_plan
                        break

                if recent_exists:
                    status = "skipped"
                    message = "Plan cognitive_loop déjà existant pour cet objectif."
                else:
                    plan = planner.create_plan(str(active_goal))
                    plan_data = plan.to_dict()
                    plan_data["approved"] = False
                    plan_data["approval_required"] = True
                    plan_data["source"] = "cognitive_loop"

                    task_manager = get_task_manager()
                    created_tasks = task_manager.create_tasks_from_plan(plan_data)

                    plan_data["tasks_generated"] = True
                    plan_data["generated_task_ids"] = [
                        task.get("id")
                        for task in created_tasks
                    ]

                    storage.save(plan_data)

                    status = "success"
                    message = "Plan généré automatiquement depuis la Cognitive Loop et converti en tâches."

        elif action == "continue_monitoring":
            status = "success"
            message = "Surveillance cognitive poursuivie."

        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "target": target,
            "priority": priority,
            "status": status,
            "message": message,
            "runtime_mode": runtime_mode,
            "runtime_policy": runtime_policy,
        }

        if action == "generate_task_plan" and status == "success":
            result["generated_plan_id"] = plan_data.get("id")
            result["generated_plan_goal"] = plan_data.get("goal")

        self._save_execution(
            result
        )

        return result

    def _save_execution(
        self,
        payload: dict[str, Any],
    ) -> None:

        ACTION_HISTORY_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        append_jsonl(ACTION_HISTORY_PATH, payload)


_action_executor: ActionExecutor | None = None


def get_action_executor() -> ActionExecutor:
    global _action_executor

    if _action_executor is None:
        _action_executor = ActionExecutor()

    return _action_executor
