from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.paths import NERON_DATA_DIR, NERON_ROOT, NERON_WORKSPACE_DIR
from agents.factory.agent_state import is_disabled as is_agent_disabled
from agents.factory.agent_state import set_enabled as set_agent_state
from agents.factory.registry import DEFAULT_GENERATED_AGENTS, DynamicAgentRegistry
from agents.factory.promotion import AgentPromotionService
from agents.factory.validator import validate_agent
from agents.runtime.runtime import get_agent_runtime
from modules.evolution.codex_runner import CodexRunner, redact_secrets


_WORKSPACE_ROOT = Path(os.getenv("NERON_WORKSPACE", str(NERON_WORKSPACE_DIR)))
_DATA_ROOT = NERON_DATA_DIR
DEFAULT_WORKSPACE_AGENTS = _WORKSPACE_ROOT / "agents"
DEFAULT_WORKSPACE_TESTS = _WORKSPACE_ROOT / "agent_tests"
DEFAULT_BACKUPS_DIR = _DATA_ROOT / "agent_backups"
DEFAULT_PROJECT_ROOT = Path(os.getenv("NERON_PROJECT_ROOT", str(NERON_ROOT)))

PROTECTED_AGENTS = {
    "event_countdown_agent",
    "meteo_agent",
    "test_agent",
    "validation_goal_pipeline_agent",
}


class AgentManager:
    def __init__(
        self,
        *,
        generated_agents: Path = DEFAULT_GENERATED_AGENTS,
        workspace_agents: Path = DEFAULT_WORKSPACE_AGENTS,
        workspace_tests: Path = DEFAULT_WORKSPACE_TESTS,
        backups_dir: Path = DEFAULT_BACKUPS_DIR,
        project_root: Path = DEFAULT_PROJECT_ROOT,
        python_executable: str | None = None,
        runtime_manager: Any | None = None,
        codex_runner: Any | None = None,
    ) -> None:
        self.generated_agents = generated_agents
        self.workspace_agents = workspace_agents
        self.workspace_tests = workspace_tests
        self.backups_dir = backups_dir
        self.project_root = project_root
        self.python_executable = python_executable or sys.executable
        self.runtime_manager = runtime_manager or get_agent_runtime()
        self.codex_runner = codex_runner

    def list_managed_agents(self) -> dict[str, Any]:
        records = self._registry().list_agent_records()
        agents = [self._status_from_record(record) for record in sorted(records, key=lambda item: str(item.get("module_name")))]
        return {"status": "ok", "count": len(agents), "agents": agents}

    def get_agent_status(self, agent_name: str) -> dict[str, Any]:
        name = self._normalize_agent_name(agent_name)
        path = self._agent_path(name)
        if not path.exists():
            return {"status": "not_found", "agent": name, "exists": False}

        record = self._record_for(name)
        validation = validate_agent(str(path))
        runtime_state = self.runtime_manager.get_state(name)
        return {
            "status": "ok",
            "agent": name,
            "exists": True,
            "protected": self._is_protected(name),
            "enabled": not is_agent_disabled(self.generated_agents, name),
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": self._sha256(path),
            "validation": validation,
            "registry": record,
            "runtime_state": runtime_state,
            "backups": self._list_backups(name),
        }

    def backup_agent(self, agent_name: str) -> dict[str, Any]:
        name = self._normalize_agent_name(agent_name)
        path = self._agent_path(name)
        if not path.exists():
            return {"status": "not_found", "agent": name, "backup_created": False}

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target_dir = self.backups_dir / name
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = target_dir / f"{timestamp}_{path.name}"
        shutil.copy2(path, destination)
        return {
            "status": "ok",
            "agent": name,
            "backup_created": True,
            "backup_path": str(destination),
            "source_path": str(path),
            "sha256": self._sha256(destination),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def inspect_agent(self, agent_name: str) -> dict[str, Any]:
        status = self.get_agent_status(agent_name)
        if status.get("status") != "ok":
            return status

        path = Path(str(status["path"]))
        content = path.read_text(encoding="utf-8")
        return {
            **status,
            "source_preview": content[:4000],
            "lines": len(content.splitlines()),
            "contains_agent_class": "class Agent" in content,
            "contains_execute": "async def execute" in content,
        }

    def delete_agent(self, agent_name: str) -> dict[str, Any]:
        name = self._normalize_agent_name(agent_name)
        if self._is_protected(name):
            return {
                "status": "refused",
                "agent": name,
                "reason": "protected_agent",
                "protected": True,
                "deleted": False,
            }

        path = self._agent_path(name)
        if not path.exists():
            return {"status": "not_found", "agent": name, "deleted": False}

        backup = self.backup_agent(name)
        if backup.get("backup_created") is not True:
            return {
                "status": "failed",
                "agent": name,
                "reason": "backup_required",
                "backup": backup,
                "deleted": False,
            }

        path.unlink()
        runtime_reload = self.runtime_manager.reload()
        return {
            "status": "deleted",
            "agent": name,
            "deleted": True,
            "backup": backup,
            "runtime_reload": runtime_reload,
        }

    def set_agent_enabled(self, agent_name: str, enabled: bool) -> dict[str, Any]:
        """Active ou désactive un agent, de façon persistante.

        Un agent désactivé reste sur disque mais le runtime refuse de
        l'exécuter (agent_disabled:<nom>) et goal_engine ne le sélectionne
        plus. Exposé par neronGoal : POST /agents/{nom}/enable|disable.
        """
        name = self._normalize_agent_name(agent_name)
        if self._is_protected(name):
            return {
                "status": "refused",
                "agent": name,
                "reason": "protected_agent",
                "protected": True,
                "enabled": None,
            }
        if not self._agent_path(name).exists():
            return {"status": "not_found", "agent": name, "enabled": None}

        disabled = set_agent_state(self.generated_agents, name, enabled)
        return {
            "status": "enabled" if enabled else "disabled",
            "agent": name,
            "enabled": name not in disabled,
        }

    def revise_agent(self, agent_name: str) -> dict[str, Any]:
        return self._not_implemented(agent_name, "revise")

    async def update_agent(self, agent_name: str, request: str = "") -> dict[str, Any]:
        name = self._normalize_agent_name(agent_name)
        update_request = str(request or "").strip()
        if self._is_protected(name):
            return {
                "status": "refused",
                "agent": name,
                "reason": "protected_agent",
                "protected": True,
                "updated": False,
            }
        if not update_request:
            return {"status": "refused", "agent": name, "reason": "request_required", "updated": False}

        production_agent = self._agent_path(name)
        if not production_agent.exists():
            return {"status": "not_found", "agent": name, "exists": False, "updated": False}

        backup = self.backup_agent(name)
        if backup.get("backup_created") is not True:
            return {
                "status": "failed",
                "agent": name,
                "reason": "backup_required",
                "backup": backup,
                "updated": False,
            }

        workspace_agent = self.workspace_agents / f"{name}.py"
        workspace_test = self.workspace_tests / f"test_{name}.py"
        self.workspace_agents.mkdir(parents=True, exist_ok=True)
        self.workspace_tests.mkdir(parents=True, exist_ok=True)
        shutil.copy2(production_agent, workspace_agent)
        self._write_update_smoke_test(name, workspace_agent, workspace_test)

        snapshot = self._snapshot_generated_agents()
        # Codex travaille dans l'espace de travail (copies de l'agent et de son
        # test), plus à la racine du projet : en mode « workspace-write », il
        # ne peut écrire que là. Son environnement est expurgé des secrets
        # (codex_runner.scrubbed_environment).
        runner = self.codex_runner or CodexRunner(
            workspace=self.workspace_agents.parent
            if self.workspace_agents.parent == self.workspace_tests.parent
            else self.project_root
        )
        codex_result = await runner.run_codex(
            self._codex_update_prompt(name, update_request, workspace_agent, workspace_test),
            f"agent_update_{name}",
        )
        codex_payload = self._safe_codex_result(codex_result)

        if self._generated_agents_changed(snapshot):
            self._restore_generated_agents(snapshot)
            return {
                "status": "failed",
                "agent": name,
                "reason": "codex_generated_dir_write_blocked",
                "backup": backup,
                "workspace_agent": str(workspace_agent),
                "workspace_test": str(workspace_test),
                "codex_result": codex_payload,
                "updated": False,
            }

        if not getattr(codex_result, "ok", False):
            return {
                "status": "failed",
                "agent": name,
                "reason": self._codex_error(codex_payload),
                "backup": backup,
                "workspace_agent": str(workspace_agent),
                "workspace_test": str(workspace_test),
                "codex_result": codex_payload,
                "updated": False,
            }

        missing = [str(path) for path in (workspace_agent, workspace_test) if not path.exists()]
        if missing:
            return {
                "status": "failed",
                "agent": name,
                "reason": f"codex_missing_files: {', '.join(missing)}",
                "backup": backup,
                "codex_result": codex_payload,
                "updated": False,
            }

        validation = validate_agent(str(workspace_agent))
        if not validation.get("ok"):
            return {
                "status": "failed",
                "agent": name,
                "reason": str(validation.get("error") or "validation_failed"),
                "backup": backup,
                "validation": validation,
                "updated": False,
            }

        compile_result = self._run_command(
            [self.python_executable, "-m", "py_compile", str(workspace_agent)],
            "compile_agent_update",
        )
        if compile_result["returncode"] != 0:
            return {
                "status": "failed",
                "agent": name,
                "reason": compile_result["stderr_tail"] or "compile_failed",
                "backup": backup,
                "compile_result": compile_result,
                "updated": False,
            }

        test_result = self._run_command(
            [self.python_executable, "-m", "pytest", "-q", str(workspace_test)],
            "pytest_agent_update",
        )
        if test_result["returncode"] != 0:
            return {
                "status": "failed",
                "agent": name,
                "reason": test_result["stdout_tail"] or test_result["stderr_tail"] or "tests_failed",
                "backup": backup,
                "compile_result": compile_result,
                "test_result": test_result,
                "updated": False,
            }

        promotion = AgentPromotionService(
            generated_dir=self.generated_agents,
        ).promote(
            workspace_agent,
            requested_by="agent_manager_update",
        )
        if not promotion.get("ok"):
            return {
                "status": "failed",
                "agent": name,
                "reason": str(promotion.get("error") or "promotion_failed"),
                "backup": backup,
                "compile_result": compile_result,
                "test_result": test_result,
                "promotion": promotion,
                "updated": False,
            }

        runtime_reload = self.runtime_manager.reload()
        return {
            "status": "updated",
            "agent": name,
            "updated": True,
            "request": update_request,
            "backup": backup,
            "workspace_agent": str(workspace_agent),
            "workspace_test": str(workspace_test),
            "codex_result": codex_payload,
            "validation": validation,
            "compile_result": compile_result,
            "test_result": test_result,
            "promotion": promotion,
            "runtime_reload": runtime_reload,
        }

    def rename_agent(self, agent_name: str, new_name: str = "") -> dict[str, Any]:
        name = self._normalize_agent_name(agent_name)
        if self._is_protected(name):
            return {"status": "refused", "agent": name, "reason": "protected_agent", "protected": True}
        return self._not_implemented(name, "rename", new_name=new_name)

    def rollback_agent(self, agent_name: str, backup_path: str | None = None) -> dict[str, Any]:
        return self._not_implemented(agent_name, "rollback", backup_path=backup_path)

    def _not_implemented(self, agent_name: str, action: str, **extra: Any) -> dict[str, Any]:
        return {
            "status": "not_implemented",
            "action": action,
            "agent": self._normalize_agent_name(agent_name),
            **extra,
        }

    def _status_from_record(self, record: dict[str, Any]) -> dict[str, Any]:
        name = str(record.get("module_name") or record.get("agent_name") or "")
        path = Path(str(record.get("path") or self._agent_path(name)))
        return {
            "agent": name,
            "agent_name": record.get("agent_name"),
            "path": str(path),
            "protected": self._is_protected(name),
            "exists": path.exists(),
            "spec": record.get("spec"),
            "spec_signature": record.get("spec_signature"),
        }

    def _registry(self) -> DynamicAgentRegistry:
        return DynamicAgentRegistry(self.generated_agents)

    def _record_for(self, agent_name: str) -> dict[str, Any] | None:
        for record in self._registry().list_agent_records():
            if str(record.get("module_name") or "") == agent_name:
                return record
        return None

    def _agent_path(self, agent_name: str) -> Path:
        return self.generated_agents / f"{agent_name}.py"

    def _normalize_agent_name(self, agent_name: str) -> str:
        return Path(str(agent_name).strip()).stem

    def _sandbox(self):
        if getattr(self, "_agent_sandbox", None) is None:
            from server.common.runtime.sandbox.agent_sandbox import AgentSandbox

            self._agent_sandbox = AgentSandbox(project_root=self.project_root)
        return self._agent_sandbox

    def _is_protected(self, agent_name: str) -> bool:
        return agent_name in PROTECTED_AGENTS

    def _list_backups(self, agent_name: str) -> list[dict[str, Any]]:
        backup_dir = self.backups_dir / agent_name
        if not backup_dir.exists():
            return []
        backups = []
        for path in sorted(backup_dir.glob("*.py"), reverse=True):
            backups.append(
                {
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                    "sha256": self._sha256(path),
                }
            )
        return backups

    def _sha256(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _write_update_smoke_test(self, agent_name: str, agent_file: Path, test_file: Path) -> None:
        test_file.write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "import importlib.util",
                    "import pathlib",
                    "import pytest",
                    f"AGENT_FILE = pathlib.Path({str(agent_file)!r})",
                    "",
                    "def load_agent():",
                    "    spec = importlib.util.spec_from_file_location('agent_under_update', AGENT_FILE)",
                    "    module = importlib.util.module_from_spec(spec)",
                    "    assert spec and spec.loader",
                    "    spec.loader.exec_module(module)",
                    "    return module.Agent()",
                    "",
                    "@pytest.mark.asyncio",
                    "async def test_agent_update_smoke():",
                    "    agent = load_agent()",
                    f"    assert agent.name == {agent_name!r}",
                    "    result = await agent.execute(text='smoke test')",
                    "    assert result is not None",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def _codex_update_prompt(
        self,
        agent_name: str,
        request: str,
        agent_file: Path,
        test_file: Path,
    ) -> str:
        try:
            generated_path = self.generated_agents.resolve().relative_to(
                self.project_root.resolve()
            )
        except ValueError:
            generated_path = self.generated_agents
        return "\n".join(
            [
                "Mission: improve an existing Neron OS generated agent.",
                "",
                "Strict constraints:",
                "- Edit only the workspace files listed below.",
                f"- Do not write to {generated_path} or any production agent path.",
                "- Do not read or print secrets.",
                "- Keep the public Agent contract: class Agent, name attribute, async execute().",
                "- Update or extend the pytest file to cover the requested improvement.",
                "",
                f"Agent name: {agent_name}",
                f"Improvement request: {request}",
                f"Write updated agent only at {agent_file}",
                f"Write updated test only at {test_file}",
            ]
        )

    def _safe_codex_result(self, result: Any) -> dict[str, Any]:
        data = result.to_dict() if hasattr(result, "to_dict") else dict(result or {})
        command = list(data.get("command") or [])
        if command and command[-1] and len(str(command[-1])) > 80:
            command[-1] = "[PROMPT_REDACTED]"
        data["command"] = command
        for key in ("stdout", "stderr"):
            data[key] = redact_secrets(str(data.get(key) or ""))
        return data

    def _codex_error(self, payload: dict[str, Any]) -> str:
        error = payload.get("stderr") or payload.get("stdout") or "codex_failed"
        return redact_secrets(str(error))[:1000]

    def _run_command(self, command: list[str], name: str) -> dict[str, Any]:
        if name.startswith("pytest_agent"):
            # Tests de l'agent modifié : ils exécutent son code. Dans le bac à
            # sable, comme pour la construction (build_orchestrator), et non
            # plus dans un pytest héritant de tout l'environnement (secrets).
            return self._sandbox().run_pytest(command[-1], timeout=120, name=name)
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            stdout = redact_secrets(completed.stdout or "")
            stderr = redact_secrets(completed.stderr or "")
            return {
                "name": name,
                "command": command,
                "returncode": completed.returncode,
                "stdout_tail": stdout[-4000:],
                "stderr_tail": stderr[-4000:],
            }
        except Exception as exc:
            return {
                "name": name,
                "command": command,
                "returncode": 1,
                "stdout_tail": "",
                "stderr_tail": redact_secrets(str(exc)),
            }

    def _snapshot_generated_agents(self) -> dict[str, bytes]:
        if not self.generated_agents.exists():
            return {}
        return {
            path.name: path.read_bytes()
            for path in self.generated_agents.glob("*.py")
            if path.is_file()
        }

    def _generated_agents_changed(self, snapshot: dict[str, bytes]) -> bool:
        return self._snapshot_generated_agents() != snapshot

    def _restore_generated_agents(self, snapshot: dict[str, bytes]) -> None:
        self.generated_agents.mkdir(parents=True, exist_ok=True)
        for path in self.generated_agents.glob("*.py"):
            if path.name not in snapshot:
                path.unlink()
        for name, content in snapshot.items():
            path = self.generated_agents / name
            if not path.exists() or path.read_bytes() != content:
                path.write_bytes(content)
