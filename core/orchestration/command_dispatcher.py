"""Dispatcher de commandes de l'Agent Patron (Core).

Le Core ne gère que les commandes qui lui appartiennent (évolution).
Les commandes Goal (/goal, /approve, /execute, objectif actif) relèvent du
Manager de chantier : elles ne sont plus dispatchées ici et retournent
`unknown_command`. Aucune interface de délégation n'est inventée dans ce module.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from modules.evolution.supervisor import (
    format_proposals_for_telegram,
    get_evolution_supervisor,
)


def _normalize(text: str) -> str:
    n = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in n if unicodedata.category(c) != "Mn")


class NeronCommandDispatcher:
    def __init__(self, *, evolution_supervisor_factory=get_evolution_supervisor) -> None:
        self.evolution_supervisor_factory = evolution_supervisor_factory

    async def dispatch(self, command: dict[str, Any]) -> dict[str, Any]:
        command_type = str(command.get("type") or "")
        source = str(command.get("source") or "system")
        user_id = str(command.get("user_id") or source)
        payload = command.get("payload")

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
