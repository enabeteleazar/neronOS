"""Isolation du code généré (outils, agents, Codex).

Avant :
- les outils générés étaient importés dans le processus du service, avec ses
  secrets, ses droits et son réseau ; leurs tests héritaient de tout
  l'environnement ;
- en mode « auto », faute d'utilisateur neron-agent et de bubblewrap, le bac
  à sable retombait sur un crochet d'audit Python (pas une frontière : même
  utilisateur, lecture de secrets.env possible, contournable par ctypes) ;
- Codex travaillait dans le dépôt en production, avec tous les secrets, et
  le superviseur poussait directement sa branche courante.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from server.common.runtime.sandbox import agent_sandbox as sb
from server.common.runtime.sandbox.agent_sandbox import AgentSandbox


@pytest.fixture
def secrets(tmp_path, monkeypatch):
    """Un faux secrets.env et un faux dossier de données, déclarés sensibles."""
    secret_file = tmp_path / "secrets.env"
    secret_file.write_text("NERON_API_KEY=ne-doit-jamais-sortir\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "gateways_tokens.sqlite3").write_text("refresh-token", encoding="utf-8")
    monkeypatch.setattr(sb, "sensitive_paths", lambda: [secret_file.resolve(), data_dir.resolve()])
    return secret_file, data_dir


def _sandbox(tmp_path, backend="python"):
    return AgentSandbox(project_root=Path(__file__).resolve().parents[1], workspace=tmp_path / "ws", backend=backend)


def _write_tool(tmp_path, body: str) -> Path:
    tool = tmp_path / "outil_genere.py"
    tool.write_text(
        "from tools.models import ToolResult\n\n\n" + body,
        encoding="utf-8",
    )
    return tool


# ── Refus par défaut ────────────────────────────────────────────────────────


def test_auto_mode_refuses_without_real_isolation(tmp_path, monkeypatch):
    sandbox = _sandbox(tmp_path, backend="auto")
    # Ni utilisateur neron-agent (systemd), ni bubblewrap.
    monkeypatch.setattr(sandbox, "_backend_used", "python")
    monkeypatch.setattr(sandbox, "_bwrap_available", False)
    tool = _write_tool(tmp_path, "def execute(payload):\n    return ToolResult(ok=True, response='exécuté')\n")

    outcome = sandbox.execute_tool(tool, {})

    assert outcome["ok"] is False
    assert outcome["error"] == "agent_sandbox_isolation_unavailable"


# ── Masquage des chemins sensibles ──────────────────────────────────────────


def test_bubblewrap_masks_secrets_and_data(tmp_path, secrets):
    secret_file, data_dir = secrets
    sandbox = _sandbox(tmp_path)
    sandbox._bwrap = "/usr/bin/bwrap"
    command = sandbox._bwrap_command(["python3", "runner.py"], tmp_path / "ws" / ".sandbox_tmp")

    joined = " ".join(command)
    assert f"--ro-bind /dev/null {secret_file.resolve()}" in joined
    assert f"--tmpfs {data_dir.resolve()}" in joined
    # Les masques viennent après la racine en lecture seule, avant l'espace de travail.
    assert command.index("--tmpfs") > command.index("/") and command.index("--tmpfs") < command.index("--bind")


def test_systemd_makes_secrets_inaccessible(tmp_path, secrets):
    secret_file, _ = secrets
    command = _sandbox(tmp_path)._systemd_command(["python3", "runner.py"], 10)
    assert f"--property=InaccessiblePaths=-{secret_file.resolve()}" in command


def test_paths_needed_by_the_sandbox_are_never_masked(tmp_path, monkeypatch):
    sandbox = _sandbox(tmp_path)
    monkeypatch.setattr(sb, "sensitive_paths", lambda: [Path(sys.prefix).resolve(), sandbox.project_root])
    assert sandbox._masked_paths() == []


# ── Mode Python explicite : défense en profondeur ───────────────────────────


def test_generated_tool_runs_without_secrets_in_its_environment(tmp_path, monkeypatch, secrets):
    monkeypatch.setenv("NERON_API_KEY", "ne-doit-jamais-sortir")
    tool = _write_tool(
        tmp_path,
        "import os\n\n\ndef execute(payload):\n"
        "    return ToolResult(ok=True, data={'cle': os.environ.get('NERON_API_KEY'), 'x': payload['x']})\n",
    )
    outcome = _sandbox(tmp_path).execute_tool(tool, {"x": 3})
    assert outcome["ok"] is True, outcome
    assert outcome["result"]["data"] == {"cle": None, "x": 3}


@pytest.mark.parametrize(
    "attempt",
    [
        "open(SECRET).read()",
        "open(DATA + '/gateways_tokens.sqlite3').read()",
        "__import__('ctypes').CDLL(None)",
        "__import__('subprocess').run(['true'])",
        "__import__('socket').create_connection(('1.1.1.1', 80))",
    ],
)
def test_sensitive_actions_are_blocked(tmp_path, secrets, attempt):
    secret_file, data_dir = secrets
    tool = _write_tool(
        tmp_path,
        f"SECRET = {str(secret_file)!r}\nDATA = {str(data_dir)!r}\n\n\n"
        f"def execute(payload):\n    return ToolResult(ok=True, response=str({attempt}))\n",
    )
    outcome = _sandbox(tmp_path).execute_tool(tool, {})
    assert outcome["ok"] is False
    assert "blocked" in str(outcome["error"]) or "Permission" in str(outcome["error"])
    assert "ne-doit-jamais-sortir" not in str(outcome)


# ── Outils générés : plus jamais importés dans le service ───────────────────


async def test_tool_runtime_executes_generated_tools_in_the_sandbox(tmp_path, monkeypatch):
    from tools import sandboxed

    calls = []

    class _Sandbox:
        def execute_tool(self, path, payload):
            calls.append((Path(path).name, payload))
            return {"ok": True, "result": {"ok": True, "response": "isolé"}}

    monkeypatch.setattr(sandboxed, "_sandbox", lambda: _Sandbox())
    tool = _write_tool(tmp_path, "MARQUEUR = []\n\n\ndef execute(payload):\n    MARQUEUR.append(1)\n")

    handler = sandboxed.sandboxed_handler(tool)
    assert await handler({"a": 1}) == {"ok": True, "response": "isolé"}
    assert calls == [("outil_genere.py", {"a": 1})]
    assert "neron_sandbox_tool" not in sys.modules and "generated_tool_outil_genere" not in sys.modules


def test_tool_without_execute_is_rejected_statically(tmp_path):
    from tools.sandboxed import sandboxed_handler

    tool = tmp_path / "sans_execute.py"
    tool.write_text("raise SystemExit('jamais exécuté')\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="generated_tool_execute_missing"):
        sandboxed_handler(tool)


def test_generated_tool_tests_run_in_the_sandbox(tmp_path, monkeypatch):
    from tools import sandboxed

    seen = []

    class _Sandbox:
        def run_pytest(self, path, timeout, name):
            seen.append(name)
            return {"returncode": 1, "stdout_tail": "1 failed"}

    monkeypatch.setattr(sandboxed, "_sandbox", lambda: _Sandbox())
    with pytest.raises(RuntimeError, match="tool_tests_failed:1 failed"):
        sandboxed.run_tool_tests(tmp_path / "test_x.py")
    assert seen == ["pytest_generated_tool"]


def test_agent_update_tests_run_in_the_sandbox(tmp_path, monkeypatch):
    from agents.factory.agent_manager import AgentManager

    manager = AgentManager(generated_agents=tmp_path, runtime_manager=object())

    class _Sandbox:
        def run_pytest(self, path, timeout, name):
            return {"name": name, "returncode": 0, "path": str(path)}

    monkeypatch.setattr(manager, "_sandbox", lambda: _Sandbox())
    result = manager._run_command([sys.executable, "-m", "pytest", "-q", "test_a.py"], "pytest_agent_update")
    assert result == {"name": "pytest_agent_update", "returncode": 0, "path": "test_a.py"}


# ── Codex : secrets retirés, copie isolée, jamais la branche vivante ───────


def test_codex_environment_has_no_secrets():
    from modules.evolution.codex_runner import scrubbed_environment

    env = scrubbed_environment({
        "PATH": "/usr/bin", "HOME": "/home/neron", "OPENAI_API_KEY": "codex", "CODEX_HOME": "/c",
        "NERON_API_KEY": "x", "TELEGRAM_BOT_TOKEN": "x", "TWILIO_AUTH_TOKEN": "x",
        "NERON_GATEWAY_GOOGLE_CLIENT_SECRET": "x", "NERON_GATEWAYS_API_KEY": "x", "DB_PASSWORD": "x",
    })
    assert env == {"PATH": "/usr/bin", "HOME": "/home/neron", "OPENAI_API_KEY": "codex", "CODEX_HOME": "/c"}


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


async def test_codex_works_on_an_isolated_branch_never_on_the_live_repo(tmp_path, monkeypatch):
    from modules.evolution.codex_runner import CodexRunner

    remote = tmp_path / "remote.git"
    live = tmp_path / "live"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "develop", str(live)], check=True)
    for key, value in (("user.email", "t@t"), ("user.name", "t")):
        _git(live, "config", key, value)
    (live / "README.md").write_text("vivant\n", encoding="utf-8")
    _git(live, "add", "."); _git(live, "commit", "-qm", "init")
    _git(live, "remote", "add", "origin", str(remote))
    monkeypatch.setenv("NERON_EVOLUTION_WORKTREES", str(tmp_path / "evolutions"))

    runner = CodexRunner(workspace=live, dry_run=False)
    assert (await runner.commit_and_push("sans copie"))["error"] == "evolution_checkout_not_isolated"

    checkout = await runner.prepare_isolated_checkout("run 42")
    assert checkout["ok"] and checkout["branch"] == "evolution/run-42"
    Path(checkout["path"], "README.md").write_text("modifié par Codex\n", encoding="utf-8")
    result = await runner.commit_and_push("evolution: test")
    runner.cleanup_isolated_checkout()

    assert result["pushed"] and result["branch"] == "evolution/run-42" and result["review_required"]
    assert (live / "README.md").read_text(encoding="utf-8") == "vivant\n"      # dépôt vivant intact
    assert _git(live, "branch", "--show-current") == "develop"
    assert "evolution/run-42" in _git(remote, "branch", "--list")            # branche à relire
    assert "develop" not in _git(remote, "branch", "--list")                 # rien poussé sur develop
    assert not Path(checkout["path"]).exists()
