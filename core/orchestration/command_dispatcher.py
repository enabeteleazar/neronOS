from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

from modules.evolution.supervisor import (
    format_proposals_for_telegram,
    get_evolution_supervisor,
)
from goal.goals.goal_manager import get_goal_manager
from goal.goals.goal_orchestrator import get_goal_orchestrator
from core.pipeline.orchestrator import CoreOrchestrator
from goal.planning.storage import PlanStorage


def _normalize(text: str) -> str:
    n = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in n if unicodedata.category(c) != "Mn")


class NeronCommandDispatcher:
    def __init__(
        self,
        *,
        goal_orchestrator_factory=get_goal_orchestrator,
        evolution_supervisor_factory=get_evolution_supervisor,
        plan_storage_factory=PlanStorage,
        goals_state_path: Path = Path("/etc/neron/data/goals_state.json"),
        goal_manager_factory=get_goal_manager,
    ) -> None:
        self.goal_orchestrator_factory = goal_orchestrator_factory
        self.evolution_supervisor_factory = evolution_supervisor_factory
        self.plan_storage_factory = plan_storage_factory
        # Retained for constructor compatibility; GoalManager is authoritative.
        self.goals_state_path = goals_state_path
        self.goal_manager_factory = goal_manager_factory

    async def dispatch(self, command: dict[str, Any]) -> dict[str, Any]:
        command_type = str(command.get("type") or "")
        source = str(command.get("source") or "system")
        user_id = str(command.get("user_id") or source)
        payload = command.get("payload")

        if command_type == "goal_request":
            return await self._goal_request(str(payload or ""), source=source)
        if command_type == "approve_plan":
            return await self._approve_plan(str(payload or ""), user_id=user_id)
        if command_type == "execute_plan":
            return await self._execute_plan(str(payload or ""), user_id=user_id)
        if command_type == "active_goal":
            return self._active_goal()
        if command_type == "evolution_text":
            return {
                "status": "ok",
                "messages": [
                    await self.route_evolution_text(
                        str(payload or ""),
                        source_channel=source,
                        user_id=user_id,
                        supervisor=command.get("supervisor"),
                    )
                ],
            }

        return {"status": "unknown_command", "messages": []}

    async def route_evolution_text(
        self,
        text: str,
        *,
        source_channel: str = "telegram",
        user_id: str = "telegram",
        supervisor: Any | None = None,
    ) -> str | None:
        supervisor = supervisor or self.evolution_supervisor_factory()
        raw = text.strip()
        normalized = _normalize(raw)

        wants_proposals = normalized in {
            "propose les prochaines evolutions",
            "quelles sont les prochaines evolutions",
            "quelles sont les prochaines evolutions ?",
        } or (
            "prochaines evolutions" in normalized
            and any(token in normalized for token in ("propose", "quelles", "liste"))
        )
        if wants_proposals or normalized == "/evolution propose":
            proposals = supervisor.generate_proposals()
            return format_proposals_for_telegram(proposals)

        if normalized in {"/evolution status", "/evolution_status", "evolution status"}:
            status = supervisor.status()
            active = status.get("active_run")
            if active:
                return (
                    "Évolution en cours\n"
                    f"Run : {active.get('run_id')}\n"
                    f"Statut : {active.get('status')}\n"
                    f"Étape : {active.get('current_step')}\n"
                    f"Progression : {active.get('progress')}%"
                )
            return f"Aucune mission d'évolution active. Propositions disponibles : {len(status.get('latest_proposals') or [])}"

        if normalized.startswith("/accept_evolution "):
            proposal_id = raw.split(maxsplit=1)[1].strip()
            result = await supervisor.accept_proposal(
                proposal_id,
                source_channel=source_channel,
                accepted_by=user_id,
            )
            return self.format_evolution_result(result)

        if normalized.startswith("/reject_evolution "):
            proposal_id = raw.split(maxsplit=1)[1].strip()
            result = supervisor.reject_proposal(
                proposal_id,
                source_channel=source_channel,
                rejected_by=user_id,
            )
            return self.format_evolution_result(result)

        if normalized in {"/evolution_stop", "evolution stop", "/evolution stop"}:
            result = await supervisor.stop()
            return self.format_evolution_result(result)

        return None

    def format_evolution_result(self, result: dict[str, Any]) -> str:
        status = result.get("status")
        if status == "accepted" and result.get("message"):
            return str(result["message"])
        if status == "not_found":
            return "Proposition introuvable."
        if status == "refused" and result.get("reason") == "evolution_run_already_active":
            active = result.get("active_run") or {}
            return (
                "Une mission d'évolution est déjà active.\n"
                f"Run : {active.get('run_id')}\n"
                f"Étape : {active.get('current_step')}"
            )
        if status == "rejected":
            proposal = result.get("proposal") or {}
            return f"Proposition refusée : {proposal.get('proposal_id')} - {proposal.get('title')}"
        if status == "stopped":
            return "Évolution stoppée. Aucune nouvelle mission ne sera lancée sans validation."

        run = result.get("run") or {}
        project = result.get("project") or {}
        lines = [
            f"Évolution {status}",
            f"Run : {run.get('run_id')}",
            f"Projet : {project.get('project_id')}",
            f"Étape : {run.get('current_step')}",
        ]
        if run.get("error"):
            lines.append(f"Erreur : {run.get('error')}")
        if run.get("commit_hash"):
            lines.append(f"Commit : {run.get('commit_hash')}")
        if status == "completed":
            lines.append("Nouvelles propositions générées. En attente de validation.")
        return "\n".join(line for line in lines if line and not line.endswith(": None"))

    async def _goal_request(self, title: str, *, source: str) -> dict[str, Any]:
        title = title.strip()
        if not title:
            return {"status": "invalid", "messages": ["Usage : /goal <objectif>"]}

        result = await CoreOrchestrator(
            goal_orchestrator_factory=self.goal_orchestrator_factory,
        ).run_goal(title, source=source)
        return {
            "status": result.get("status"),
            "result": result,
            "messages": [self._format_goal_result(result)],
        }

    async def _approve_plan(self, plan_id: str, *, user_id: str) -> dict[str, Any]:
        wanted = plan_id.strip()
        if not wanted:
            return {"status": "invalid", "messages": ["Usage : /approve <plan_id>"]}

        orchestrator = self.goal_orchestrator_factory()
        plan = orchestrator.find_plan(wanted)
        if not plan:
            return {"status": "not_found", "messages": ["❌ Plan introuvable."]}

        messages = [
            f"✅ Plan approuvé : {str(plan.get('id'))[:8]}\n"
            f"⚙ Exécution contrôlée démarrée\nObjectif : {plan.get('goal')}"
        ]
        result = await orchestrator.execute_approved_plan(wanted, approved_by=user_id)
        messages.append(self._format_execution_result(result, plan))
        return {"status": result.get("status"), "result": result, "messages": messages}

    async def _execute_plan(self, plan_id: str, *, user_id: str) -> dict[str, Any]:
        wanted = plan_id.strip()
        if not wanted:
            return {"status": "invalid", "messages": ["Usage : /execute <plan_id>"]}

        orchestrator = self.goal_orchestrator_factory()
        plan = orchestrator.find_plan(wanted)
        if not plan:
            return {"status": "not_found", "messages": ["❌ Plan introuvable."]}
        if plan.get("approved") is not True:
            return {
                "status": "not_approved",
                "messages": [f"⛔ Plan non approuvé. Utilise d'abord : /approve {str(plan.get('id'))[:8]}"],
            }

        result = await orchestrator.execute_plan(plan, approved_by=user_id)
        return {"status": result.get("status"), "result": result, "messages": [self._format_execute_result(result, plan)]}

    def _active_goal(self) -> dict[str, Any]:
        goal = self.goal_manager_factory().get_active_goal()
        if goal:
            return {
                "status": "ok",
                "messages": [
                    f"🎯 Objectif actif\n\nID : {goal.get('id')}\nTitre : {goal.get('title')}\nPriorité : {goal.get('priority')}"
                ],
            }

        return {"status": "not_found", "messages": ["Aucun objectif actif trouvé."]}

    def _format_goal_result(self, result: dict[str, Any]) -> str:
        plan = result.get("plan", {})
        risk = plan.get("risk", {})
        short_id = str(plan.get("id") or "")[:8]
        status = result.get("status")

        if status == "plan_finished":
            proposal = plan.get("agent_creation_proposal") or {}
            if plan.get("registered_agent"):
                tests = "OK" if plan.get("tests_ok") else "non vérifiés"
                runtime = "OK" if (plan.get("runtime_reload") or {}).get("ok") else "non rechargé"
                lines = [
                    "Projet terminé.",
                    f"Agent créé : {plan.get('registered_agent')}.",
                    f"Tests : {tests}.",
                    "Agent enregistré : oui.",
                    f"Runtime rechargé : {runtime}.",
                ]
                if plan.get("codex_used") is not None:
                    lines.extend(
                        [
                            f"Codex : {'utilisé' if plan.get('codex_used') else 'non utilisé'}.",
                            f"Fallback : {'oui' if plan.get('codex_fallback') else 'non'}.",
                        ]
                    )
                return "\n".join(lines)
            lines = [
                "✅ Objectif reçu",
                "🧠 Plan généré",
                "⚙ Exécution automatique autorisée",
                "🏁 Objectif terminé",
                "",
                f"ID plan : {short_id}",
                f"Risque : {risk.get('risk_level', 'low')} ({risk.get('risk_score', '?')}/100)",
            ]
            if proposal:
                lines.extend(["", f"Proposition : {proposal.get('agent_name')}", f"État : {proposal.get('status')}"])
            return "\n".join(lines)

        if status in {"partial", "failed"}:
            return (
                "✅ Objectif reçu\n"
                "🧠 Plan généré\n"
                "📄 Rapport d'exécution envoyé\n\n"
                f"ID plan : {short_id}\n"
                f"Statut : {status}"
            )

        if status == "approval_required":
            return ""

        if status == "blocked":
            return (
                "✅ Objectif reçu\n"
                "🧠 Plan généré\n"
                "🚫 Exécution bloquée par le CriticEngine\n\n"
                f"ID plan : {short_id}\n"
                f"Risque : {risk.get('risk_level', 'critical')} ({risk.get('risk_score', '?')}/100)"
            )

        return f"✅ Objectif reçu\n🧠 Plan généré\nStatut : {status}\nID plan : {short_id}"

    def _format_execution_result(self, result: dict[str, Any], fallback_plan: dict[str, Any]) -> str:
        updated = result.get("plan", fallback_plan)
        status = result.get("status")

        if status == "plan_finished":
            return f"📄 Rapport final envoyé\n\nID : {str(updated.get('id'))[:8]}\nObjectif : {updated.get('goal')}"

        if status in {"partial", "failed"}:
            return f"📄 Rapport d'exécution envoyé\n\nID : {str(updated.get('id'))[:8]}\nStatut : {status}"

        if status == "blocked":
            risk = updated.get("risk", {})
            return (
                f"🚫 Exécution interdite\n\nObjectif : {updated.get('goal')}\n"
                f"Risque : {risk.get('risk_level', 'critical')} ({risk.get('risk_score', '?')}/100)"
            )

        return f"❌ Exécution non terminée\nStatut : {status}\nErreur : {result.get('error') or updated.get('error')}"

    def _format_execute_result(self, result: dict[str, Any], fallback_plan: dict[str, Any]) -> str:
        updated = result.get("plan", fallback_plan)
        status = result.get("status")

        if status == "plan_finished":
            return f"✅ Plan exécuté\n📄 Rapport final envoyé\n\nID : {str(updated.get('id'))[:8]}\nObjectif : {updated.get('goal')}"
        if status in {"partial", "failed"}:
            return f"📄 Rapport d'exécution envoyé\n\nID : {str(updated.get('id'))[:8]}\nStatut : {status}"
        return (
            f"⚠ Exécution terminée avec statut : {status}\n\n"
            f"ID : {str(updated.get('id'))[:8]}\nObjectif : {updated.get('goal')}\n"
            f"Erreur : {result.get('error') or updated.get('error')}"
        )


_dispatcher: NeronCommandDispatcher | None = None


def get_command_dispatcher() -> NeronCommandDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = NeronCommandDispatcher()
    return _dispatcher


async def dispatch_command(command: dict[str, Any]) -> dict[str, Any]:
    return await get_command_dispatcher().dispatch(command)


async def route_evolution_text(
    text: str,
    *,
    supervisor: Any | None = None,
    source_channel: str = "telegram",
    user_id: str = "telegram",
) -> str | None:
    return await get_command_dispatcher().route_evolution_text(
        text,
        supervisor=supervisor,
        source_channel=source_channel,
        user_id=user_id,
    )
