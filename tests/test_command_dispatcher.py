from __future__ import annotations

from pathlib import Path

import pytest

from core.orchestration.command_dispatcher import NeronCommandDispatcher


class FakeEvolutionSupervisor:
    def status(self) -> dict:
        return {"active_run": {"run_id": "run-1", "status": "running", "current_step": "codex", "progress": 25}}


@pytest.mark.parametrize(
    "command_type",
    ["goal_request", "approve_plan", "execute_plan", "active_goal"],
)
async def test_dispatcher_does_not_handle_goal_commands(command_type):
    """Les commandes Goal relèvent du Manager de chantier, pas du Core."""
    result = await NeronCommandDispatcher().dispatch(
        {"source": "telegram", "type": command_type, "payload": "x", "user_id": "chat-1"}
    )

    assert result == {"status": "unknown_command", "messages": []}


async def test_dispatcher_routes_evolution_status():
    dispatcher = NeronCommandDispatcher(evolution_supervisor_factory=lambda: FakeEvolutionSupervisor())

    result = await dispatcher.dispatch(
        {
            "source": "telegram",
            "type": "evolution_text",
            "payload": "/evolution_status",
            "user_id": "chat-1",
        }
    )

    assert result["status"] == "ok"
    assert "Run : run-1" in result["messages"][0]


def test_telegram_agent_does_not_import_internal_orchestrators_directly():
    source = (
        Path(__file__).resolve().parents[1]
        / "server"
        / "agents"
        / "builtin"
        / "communication"
        / "telegram_agent.py"
    ).read_text(encoding="utf-8")

    assert "goal.goals.goal_orchestrator" not in source
    assert "modules.evolution.supervisor" not in source
    assert "from goal" not in source
    assert "CommandHandler(\"goal\"" not in source
