from __future__ import annotations

import json
from pathlib import Path

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

from modules.cognitive.critic_engine import get_critic_engine
from modules.cognitive.planner import get_planner
from modules.cognitive.reasoner import get_reasoner
from modules.cognitive.decision_engine import get_decision_engine
from modules.cognitive.action_executor import get_action_executor
try:
    from goal.system.task_manager import normalize_task_title
except ImportError:  # goal absent (service séparé)
    from common.goal_unavailable import unavailable
    normalize_task_title, = unavailable('normalize_task_title')
from server.common.runtime.governor import get_runtime_governor

@dataclass
class CognitiveState:
    timestamp: str
    self_health: str |None
    world_status: str | None
    active_goal: str | None
    active_tasks: list[dict[str, Any]]
    generated_plan: list[dict[str, Any]]
    diagnostics: list[str]
    recommendations: list[str]
    criticisms: list[str]
    cognitive_score: int
    reasoning: dict[str, Any]
    decision: dict[str, Any]
    execution_result: dict[str, Any]
    runtime_policy: dict[str, Any]
    next_action: str | None


class CognitiveCore:
    """
    Noyau cognitif minimal de Néron.

    Version v0.2 :
    - observe l'état interne
    - observe l'environnement
    - observe les objectifs
    - observe les tâches
    - produit un état cognitif unifié
    - propose une prochaine action
    """

    def __init__(
        self,
        self_model: Any = None,
        world_model: Any = None,
        goal_system: Any = None,
        task_manager: Any = None,
        memory: Any = None,
    ) -> None:
        self.self_model = self_model
        self.world_model = world_model
        self.goal_system = goal_system
        self.task_manager = task_manager
        self.memory = memory

    def evaluate(self) -> CognitiveState:
        diagnostics: list[str] = []
        recommendations: list[str] = []

        self_health = self._get_self_health()
        world_status = self._get_world_status()
        active_goal = self._get_active_goal()

        governor = get_runtime_governor()
        runtime_policy = governor.to_dict()

        runtime_mode = runtime_policy.get(
            "runtime_mode",
            "normal",
        )

        planner_enabled = runtime_policy.get(
            "planner_enabled",
            True,
        )

        heavy_reasoning_allowed = runtime_policy.get(
            "heavy_reasoning_allowed",
            True,
        )

        max_parallel_agents = runtime_policy.get(
            "max_parallel_agents",
            3,
        )

        autonomous_actions_allowed = runtime_policy.get(
            "autonomous_actions_allowed",
            True,
        )

        planner = get_planner()

        if planner_enabled and active_goal:
            generated_tasks = planner.generate_plan(
                active_goal,
                context={
                    "runtime_policy": runtime_policy,
                },
            ) or []
        else:
            generated_tasks = []

        generated_plan = generated_tasks

        diagnostics.append(
            f"Mode runtime actif : {runtime_mode}"
        )

        if not heavy_reasoning_allowed:
            recommendations.append(
                "Limiter les raisonnements complexes tant que le mode runtime reste restrictif."
            )

        if not autonomous_actions_allowed:
            recommendations.append(
                "Les actions autonomes sont temporairement limitées."
            )

        recommendations.append(
            f"Nombre maximal d'agents parallèles recommandé : {max_parallel_agents}."
        )

        if (
            self.task_manager
            and generated_tasks
            and hasattr(
                self.task_manager,
                "create_task",
            )
        ):
            existing_titles = {
                normalize_task_title(task.get("title"))
                for task in self.task_manager.list_tasks()
            }

            for task_data in generated_tasks:
                if (
                    normalize_task_title(task_data.get("title"))
                    not in existing_titles
                ):
                    self.task_manager.create_task(
                        title=task_data.get("title"),
                        description=task_data.get(
                            "description"
                        ),
                        priority=task_data.get(
                            "priority",
                            "medium",
                        ),
                        source=task_data.get(
                            "source",
                            "planner",
                        ),
                    )

        active_tasks = self._get_active_tasks()

        if self_health in {
            "warning",
            "critical",
            "stable_with_warning",
            "unknown",
        }:
            diagnostics.append(
                f"État interne non optimal : {self_health}"
            )
            recommendations.append(
                "Analyser le SelfModel avant toute action lourde."
            )

        if world_status not in {
            None,
            "stable",
            "healthy",
        }:
            diagnostics.append(
                f"Environnement instable : {world_status}"
            )
            recommendations.append(
                "Vérifier le WorldModel et les services critiques."
            )

        if not active_goal:
            diagnostics.append(
                "Aucun objectif actif détecté."
            )
            recommendations.append(
                "Définir ou restaurer un objectif actif."
            )

        if not active_tasks:
            recommendations.append(
                "Créer une tâche cognitive liée à l'objectif actif."
            )

        critic_engine = get_critic_engine()

        critic_result = critic_engine.evaluate(
            {
                "self_health": self_health,
                "world_status": world_status,
                "active_goal": active_goal,
                "active_tasks": active_tasks,
            }
        )

        reasoner = get_reasoner()

        reasoning = reasoner.reason(
            {
                "self_health": self_health,
                "world_status": world_status,
                "active_goal": active_goal,
                "active_tasks": active_tasks,
                "cognitive_score": critic_result["cognitive_score"],
                "diagnostics": diagnostics,
                "recommendations": recommendations,
                "criticisms": critic_result["criticisms"],
            }
        )

        decision_engine = get_decision_engine()

        decision = decision_engine.decide(
            reasoning
        )

        action_executor = get_action_executor()

        execution_result = action_executor.execute(
            decision=decision,
            context={
                "self_health": self_health,
                "world_status": world_status,
                "active_goal": active_goal,
                "active_tasks": active_tasks,
                "generated_plan": generated_plan,
                "reasoning": reasoning,
                "runtime_policy": runtime_policy,
            },
        )

        next_action = decision.get(
            "action"
        )

        return CognitiveState(
            timestamp=datetime.now(timezone.utc).isoformat(),
            self_health=self_health,
            world_status=world_status,
            active_goal=active_goal,
            active_tasks=active_tasks,
            generated_plan=generated_plan,
            diagnostics=diagnostics,
            recommendations=(
                recommendations
                + critic_result["recommendations"]
            ),
            criticisms=critic_result["criticisms"],
            cognitive_score=critic_result["cognitive_score"],
            reasoning=reasoning,
            decision=decision,
            execution_result=execution_result,
            runtime_policy=runtime_policy,
            next_action=next_action,
        )
    def to_dict(self) -> dict[str, Any]:
        return asdict(self.evaluate())

    def _get_self_health(self) -> str | None:
        if not self.self_model:
            return None

        if hasattr(self.self_model, "collect_runtime"):
            self.self_model.collect_runtime()

        if hasattr(self.self_model, "compute_health"):
            self.self_model.compute_health()

        if hasattr(self.self_model, "to_dict"):
            data = self.self_model.to_dict()

            return (
                data.get("health_global")
                or data.get("global_health")
                or data.get("health_status")
                or data.get("status")
                or data.get("health", {}).get("global")
                or data.get("health", {}).get("realtime")
                or data.get("runtime", {}).get("health")
                or "unknown"
            )

        return "unknown"

    def _get_world_status(self) -> str | None:
        if not self.world_model:
            return None

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        if hasattr(self.world_model, "environment_status"):
            return self.world_model.environment_status

        if hasattr(self.world_model, "to_dict"):
            data = self.world_model.to_dict()
            return (
                data.get("environment_status")
                or data.get("status")
                or "unknown"
            )

        return "unknown"

    def _get_active_goal(self) -> str | None:
        if self.goal_system:
            if hasattr(self.goal_system, "get_active_goal"):
                goal = self.goal_system.get_active_goal()

                if isinstance(goal, dict):
                    return (
                        goal.get("title")
                        or goal.get("name")
                    )

                return str(goal) if goal else None

        if self.self_model and hasattr(self.self_model, "to_dict"):
            data = self.self_model.to_dict()
            goal = data.get("active_goal")

            if isinstance(goal, dict):
                return (
                    goal.get("title")
                    or goal.get("name")
                )

            if goal:
                return str(goal)

        try:
            from goal.goals.goal_manager import get_goal_manager

            goal = get_goal_manager().get_active_goal()
            if goal:
                return goal.get("title") or goal.get("name")
        except Exception:
            pass

        return None

    def _get_active_tasks(self) -> list[dict[str, Any]]:
        if self.task_manager:
            if hasattr(self.task_manager, "list_active_tasks"):
                tasks = self.task_manager.list_active_tasks()

                return tasks if isinstance(tasks, list) else []

            if hasattr(self.task_manager, "get_active_tasks"):
                tasks = self.task_manager.get_active_tasks()

                return tasks if isinstance(tasks, list) else []

        try:
            from goal.system.task_manager import get_task_manager

            return get_task_manager().list_active_tasks()
        except Exception:
            pass

        return []
