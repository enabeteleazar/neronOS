from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from common.paths import NERON_ROOT
from modules.evolution.codex_runner import CODEX_MISSING_ERROR, CodexRunner, redact_secrets
from modules.evolution.models import EvolutionProposal
from modules.evolution.proposal_engine import ProposalEngine
from modules.evolution.storage import EvolutionStorage
try:
    from goal.projects.manager import ProjectManager, get_project_manager
except ImportError:  # goal absent (service séparé)
    from common.goal_unavailable import unavailable
    ProjectManager, get_project_manager = unavailable('ProjectManager', 'get_project_manager')


logger = logging.getLogger("neron.evolution")

EVOLUTION_ACCEPTED_BACKGROUND_MESSAGE = "Évolution acceptée. Exécution en arrière-plan."


class EvolutionSupervisor:
    def __init__(
        self,
        *,
        storage: EvolutionStorage | None = None,
        proposal_engine: ProposalEngine | None = None,
        codex_runner: CodexRunner | None = None,
        project_manager: ProjectManager | None = None,
        workspace: Path = NERON_ROOT,
        timeout_seconds: int | None = None,
        telegram_notifier: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self.storage = storage or EvolutionStorage()
        self.proposal_engine = proposal_engine or ProposalEngine(workspace)
        self.codex_runner = codex_runner or CodexRunner(workspace=workspace)
        self.project_manager = project_manager or get_project_manager()
        self.timeout_seconds = timeout_seconds or int(os.getenv("NERON_EVOLUTION_RUN_TIMEOUT", "1800"))
        self._telegram_notifier = telegram_notifier
        self._accept_lock = asyncio.Lock()
        self._background_tasks: dict[str, asyncio.Task[dict[str, Any] | None]] = {}

    def observe(self) -> dict[str, Any]:
        return self.proposal_engine.observe()

    def detect_limits(self) -> list[dict[str, Any]]:
        return self.proposal_engine.detect_limits(self.observe())

    def generate_proposals(self) -> list[dict[str, Any]]:
        observation = self.observe()
        limits = self.proposal_engine.detect_limits(observation)
        proposals = self.proposal_engine.generate_proposals(observation, limits)
        saved = self.storage.save_proposals(proposals)
        logger.info("Evolution proposals generated: %s", len(saved))
        return saved

    async def submit_proposals(self, channel: str = "api") -> dict[str, Any]:
        proposals = self.storage.latest_proposals() or self.generate_proposals()
        message = format_proposals_for_telegram(proposals)
        logger.info("Evolution proposals submitted through %s\n%s", channel, message)
        if channel == "telegram":
            await self._notify_telegram(message)
        return {"channel": channel, "proposals": proposals, "message": message}

    async def accept_proposal(
        self,
        proposal_id: str,
        *,
        source_channel: str = "api",
        accepted_by: str = "user",
        execute: bool = True,
    ) -> dict[str, Any]:
        async with self._accept_lock:
            active = self.storage.active_run()
            if active:
                return {
                    "status": "refused",
                    "reason": "evolution_run_already_active",
                    "active_run": active,
                }

            proposal = self.storage.get_proposal(proposal_id)
            if not proposal:
                return {"status": "not_found", "proposal_id": proposal_id}

            self.storage.record_decision(
                proposal,
                "accepted",
                source_channel=source_channel,
                decided_by=accepted_by,
            )
            self.storage.mark_proposal(str(proposal["proposal_id"]), "accepted")
            project = self.project_manager.create_project(
                title=str(proposal.get("title") or "Evolution Néron"),
                project_type="evolution",
                requested_by=accepted_by,
                source_channel=source_channel,
                query=str(proposal.get("summary") or ""),
                metadata={
                    "proposal_id": proposal.get("proposal_id"),
                    "title": proposal.get("title"),
                    "codex_prompt": proposal.get("codex_prompt"),
                    "tests": [],
                    "commit_hash": None,
                    "branch": None,
                },
            )
            project = self.project_manager.update_project(
                project["project_id"],
                {"status": "running"},
                step="accepted",
                step_status="done",
                progress=10,
            ) or project
            run = self.storage.create_run(
                proposal,
                project_id=project.get("project_id"),
                source_channel=source_channel,
                accepted_by=accepted_by,
            )
            run = self.storage.update_run(
                run["run_id"],
                {"status": "running", "current_step": "accepted", "progress": 10},
            ) or run

        if not execute:
            return {"status": "accepted", "run": run, "project": project}

        self._start_background_run(str(run["run_id"]))
        return {
            "status": "accepted",
            "message": EVOLUTION_ACCEPTED_BACKGROUND_MESSAGE,
            "run": run,
            "project": project,
        }

    def reject_proposal(
        self,
        proposal_id: str,
        *,
        source_channel: str = "api",
        rejected_by: str = "user",
    ) -> dict[str, Any]:
        proposal = self.storage.get_proposal(proposal_id)
        if not proposal:
            return {"status": "not_found", "proposal_id": proposal_id}
        self.storage.record_decision(
            proposal,
            "rejected",
            source_channel=source_channel,
            decided_by=rejected_by,
        )
        self.storage.mark_proposal(str(proposal["proposal_id"]), "rejected")
        return {"status": "rejected", "proposal": proposal}

    async def run_accepted_proposal(self, run_id: str) -> dict[str, Any]:
        run = self.storage.get_run(run_id)
        if not run:
            return {"status": "not_found", "run_id": run_id}

        proposal = run.get("proposal") or {}
        project_id = run.get("project_id")
        prompt = str(proposal.get("codex_prompt") or "")
        if not prompt:
            failed = self._fail_run(run, "Proposition sans prompt Codex.")
            await self._notify_telegram(_short_run_report(failed))
            return failed

        codex_status = self._codex_status()
        if not codex_status["codex_available"]:
            codex_error = str(codex_status.get("codex_error") or CODEX_MISSING_ERROR)
            failed = self._fail_run(
                run,
                codex_error,
                codex={
                    "ok": False,
                    "name": "codex",
                    "command": [],
                    "returncode": 1,
                    "stdout": "",
                    "stderr": codex_error,
                    "timed_out": False,
                },
            )
            await self._notify_telegram(_short_run_report(failed))
            return failed

        self._update_project(project_id, status="running", step="codex_running", progress=25)
        run = self._update_run(run_id, current_step="codex_running", progress=25, status="running")
        codex_result = await self.codex_runner.run_codex(prompt, run_id)
        run = self.storage.update_run(run_id, {"codex": codex_result.to_dict()}) or run
        if not codex_result.ok:
            failed = self._fail_run(run, "Codex a échoué.", codex=codex_result.to_dict())
            await self._notify_telegram(_short_run_report(failed))
            self.generate_proposals()
            return failed

        self._update_project(project_id, status="running", step="tests", progress=55)
        run = self._update_run(run_id, current_step="tests", progress=55, status="running")
        test_results = await self.codex_runner.run_tests()
        tests_payload = [result.to_dict() for result in test_results]
        run = self.storage.update_run(run_id, {"tests": tests_payload}) or run
        self._update_project(
            project_id,
            status="running",
            step="tests",
            progress=70,
            metadata_update={"tests": tests_payload},
        )
        failed_tests = [result for result in test_results if not result.ok]
        if failed_tests:
            failed = self._fail_run(run, f"Tests en échec: {failed_tests[0].name}")
            await self._notify_telegram(_short_run_report(failed))
            self.generate_proposals()
            return failed

        self._update_project(project_id, status="running", step="commit", progress=85)
        message = commit_message_for_proposal(proposal)
        commit = await self.codex_runner.commit_and_push(message)
        if not commit.get("ok"):
            failed = self._fail_run(run, "Commit/push a échoué.", commit=commit)
            await self._notify_telegram(_short_run_report(failed))
            self.generate_proposals()
            return failed

        completed = self.storage.update_run(
            run_id,
            {
                "status": "completed",
                "current_step": "completed",
                "progress": 100,
                "commit": commit,
                "commit_hash": commit.get("commit_hash"),
                "branch": commit.get("branch"),
                "error": None,
            },
        ) or run
        self._update_project(
            project_id,
            status="completed",
            step="completed",
            progress=100,
            metadata_update={
                "tests": tests_payload,
                "commit_hash": commit.get("commit_hash"),
                "branch": commit.get("branch"),
            },
        )
        await self._notify_telegram(_short_run_report(completed))
        self.generate_proposals()
        return completed

    def status(self) -> dict[str, Any]:
        status = self.storage.status()
        status.update(self._codex_status())
        return status

    async def stop(self) -> dict[str, Any]:
        self.storage.set_stopped(True)
        await self.codex_runner.cancel()
        for task in list(self._background_tasks.values()):
            task.cancel()
        active = self.storage.active_run()
        if not active:
            return {"status": "stopped", "active_run": None}
        run = self.storage.update_run(
            active["run_id"],
            {
                "status": "cancelled",
                "current_step": "cancelled",
                "error": "Evolution stoppée par l'utilisateur.",
            },
        )
        self._update_project(active.get("project_id"), status="cancelled", step="cancelled", progress=0)
        return {"status": "stopped", "active_run": run}

    def _start_background_run(self, run_id: str) -> None:
        task = asyncio.create_task(self._run_background(run_id), name=f"evolution-{run_id}")
        self._background_tasks[run_id] = task
        task.add_done_callback(lambda done_task: self._on_background_done(run_id, done_task))

    async def _run_background(self, run_id: str) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(
                self.run_accepted_proposal(run_id),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            await self.codex_runner.cancel()
            run = self.storage.get_run(run_id)
            if not run:
                return None
            failed = self._fail_run(run, f"Evolution timeout après {self.timeout_seconds}s.")
            await self._notify_telegram(_short_run_report(failed))
            self.generate_proposals()
            return failed
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            run = self.storage.get_run(run_id)
            if not run:
                logger.exception("Evolution background run failed before state was available: %s", run_id)
                return None
            failed = self._fail_run(run, f"Erreur worker EvolutionSupervisor: {exc}")
            await self._notify_telegram(_short_run_report(failed))
            self.generate_proposals()
            logger.exception("Evolution background run failed: %s", run_id)
            return failed

    def _on_background_done(
        self,
        run_id: str,
        task: asyncio.Task[dict[str, Any] | None],
    ) -> None:
        self._background_tasks.pop(run_id, None)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            logger.exception("Evolution background task ended with an unhandled error: %s", run_id)

    def _fail_run(self, run: dict[str, Any], error: str, **updates: Any) -> dict[str, Any]:
        payload = {
            "status": "failed",
            "current_step": "failed",
            "error": redact_secrets(error),
            **updates,
        }
        failed = self.storage.update_run(run["run_id"], payload) or run
        self._update_project(
            run.get("project_id"),
            status="failed",
            step="failed",
            progress=int(run.get("progress") or 0),
            error=payload["error"],
            metadata_update=self._failure_project_metadata(run, payload),
        )
        return failed

    def _failure_project_metadata(
        self,
        run: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "run_id": run.get("run_id"),
            "run_error": payload.get("error") or run.get("error"),
            "retry_requires_validation": True,
        }

        codex = payload.get("codex") or run.get("codex")
        if isinstance(codex, dict):
            context["codex"] = self._compact_command_result(codex)

        tests = payload.get("tests") or run.get("tests")
        if isinstance(tests, list) and tests:
            context["tests"] = [
                self._compact_command_result(test)
                for test in tests
                if isinstance(test, dict)
            ]

        commit = payload.get("commit") or run.get("commit")
        if isinstance(commit, dict):
            context["commit"] = self._compact_commit_result(commit)

        return {"failure_context": context}

    def _compact_commit_result(self, commit: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {
            "ok": bool(commit.get("ok")),
            "pushed": bool(commit.get("pushed")),
        }
        for key in ("add", "commit", "push", "status"):
            value = commit.get(key)
            if isinstance(value, dict):
                compact[key] = self._compact_command_result(value)
        return compact

    def _compact_command_result(self, result: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {
            "name": result.get("name"),
            "returncode": result.get("returncode"),
            "timed_out": bool(result.get("timed_out")),
            "ok": bool(result.get("ok")),
        }
        stdout_tail = self._tail_text(str(result.get("stdout") or ""))
        stderr_tail = self._tail_text(str(result.get("stderr") or ""))
        if stdout_tail:
            compact["stdout_tail"] = stdout_tail
        if stderr_tail:
            compact["stderr_tail"] = stderr_tail
        return compact

    def _tail_text(self, value: str, limit: int = 800) -> str:
        text = redact_secrets(value)
        if len(text) <= limit:
            return text
        return text[-limit:]

    def _update_run(self, run_id: str, **updates: Any) -> dict[str, Any]:
        run = self.storage.update_run(run_id, updates)
        if not run:
            raise RuntimeError(f"Evolution run introuvable: {run_id}")
        return run

    def _update_project(
        self,
        project_id: str | None,
        *,
        status: str,
        step: str,
        progress: int,
        error: str | None = None,
        metadata_update: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not project_id:
            return None
        project = self.project_manager.get_project(project_id)
        updates: dict[str, Any] = {"status": status}
        if metadata_update:
            metadata = dict((project or {}).get("metadata") or {})
            metadata.update(metadata_update)
            updates["metadata"] = metadata
        return self.project_manager.update_project(
            project_id,
            updates,
            step=step,
            step_status="done" if status not in {"failed", "cancelled"} else status,
            progress=progress,
            error=error,
        )

    def _project_for_run(self, run: dict[str, Any]) -> dict[str, Any] | None:
        project_id = run.get("project_id")
        return self.project_manager.get_project(project_id) if project_id else None

    def _codex_status(self) -> dict[str, Any]:
        status_getter = getattr(self.codex_runner, "codex_status", None)
        if callable(status_getter):
            return dict(status_getter())
        return {
            "codex_available": True,
            "codex_bin": None,
            "codex_error": None,
            "codex_version": None,
            "codex_exec_supported_options": [],
        }

    async def _notify_telegram(self, message: str) -> None:
        if self._telegram_notifier:
            await self._telegram_notifier(redact_secrets(message[:3500]))
            return
        try:
            from agents.builtin.communication.telegram_agent import send_notification

            await send_notification(redact_secrets(message[:3500]), level="info")
        except Exception as exc:
            logger.debug("Telegram evolution notification skipped: %s", exc)


def format_proposals_for_telegram(proposals: list[dict[str, Any]]) -> str:
    if not proposals:
        return "Aucune évolution proposée pour le moment."
    lines = ["Évolutions proposées :", ""]
    for index, proposal in enumerate(proposals[:3], start=1):
        display_index = int(proposal.get("index") or index)
        priority = proposal.get("priority", "future")
        title = proposal.get("title", "Sans titre")
        gain = proposal.get("expected_gain", "Gain à préciser.")
        risk = proposal.get("risk", "low")
        proposal_id = proposal.get("proposal_id", "")
        lines.extend(
            [
                f"{display_index}. [{priority}] {title}",
                f"   ID : {proposal_id}",
                f"   Gain : {gain}",
                f"   Risque : {risk}.",
                f"   Réponds : /accept_evolution {display_index}",
                "",
            ]
        )
    lines.extend(
        [
            "Commandes :",
            "/accept_evolution 1",
            "/reject_evolution 1",
            "/evolution_status",
            "/evolution_stop",
        ]
    )
    return "\n".join(lines)


def commit_message_for_proposal(proposal: dict[str, Any]) -> str:
    title = str(proposal.get("title") or "update supervised evolution").strip()
    lower_title = title[:72].lower()
    proposal_type = str(proposal.get("type") or "feature")
    prefix = {
        "bugfix": "fix(core)",
        "refactor": "refactor(core)",
        "feature": "feat(core)",
        "test": "test(core)",
        "docs": "docs",
        "security": "fix(security)",
    }.get(proposal_type, "feat(core)")
    return f"{prefix}: {lower_title}"


def _short_run_report(run: dict[str, Any]) -> str:
    title = (run.get("proposal") or {}).get("title") or run.get("proposal_id")
    status = run.get("status")
    lines = [
        f"Évolution {status}",
        f"Mission : {title}",
        f"Run : {run.get('run_id')}",
    ]
    if run.get("error"):
        lines.append(f"Erreur : {run.get('error')}")
    if run.get("commit_hash"):
        lines.append(f"Commit : {run.get('commit_hash')}")
    if run.get("branch"):
        lines.append(f"Branche : {run.get('branch')}")
    if status == "completed":
        lines.append("Nouvelles propositions générées. En attente de validation.")
    return "\n".join(lines)


_evolution_supervisor: EvolutionSupervisor | None = None


def get_evolution_supervisor() -> EvolutionSupervisor:
    global _evolution_supervisor
    if _evolution_supervisor is None:
        _evolution_supervisor = EvolutionSupervisor()
    return _evolution_supervisor
