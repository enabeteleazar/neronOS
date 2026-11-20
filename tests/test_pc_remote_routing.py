"""Routage des commandes de contrôle PC distant (48ba388, perdu avec 58ab382).

Sans détection déterministe, « ouvre htop sur mon pc distant » était lu comme
system_status et recevait un rapport d'état au lieu d'être exécuté sur le PC.
"""

from __future__ import annotations

import pytest

from core.pipeline import orchestrator as orch
from core.pipeline.intent.intent_router import Intent
from core.pipeline.orchestrator import CoreOrchestrator


@pytest.fixture(autouse=True)
def no_devices(monkeypatch):
    # Registre vide : seules les formules explicites déclenchent.
    monkeypatch.setattr("integrations.pc_remote.config.load_devices", lambda: {})


@pytest.mark.parametrize(
    "query",
    [
        "Ouvre htop sur mon PC distant",
        "Lance Firefox sur mon pc",
        "Liste les applications du pc distant",
        "Ferme le navigateur sur l'ordinateur distant",
    ],
)
async def test_pc_remote_commands_reach_the_pc_agent(query):
    decision, intent_result = await CoreOrchestrator().decide(query)
    assert decision.selected_route == "tool_router"
    assert decision.intent == Intent.PC_REMOTE.value
    assert intent_result.intent == Intent.PC_REMOTE


@pytest.mark.parametrize(
    "query",
    [
        "Ferme les volets du salon",
        "Montre mes mails",
        "Lance un minuteur de 10 minutes",
        "Ouvre ma page Notion",
        "Quel est ton état actuel ?",
    ],
)
async def test_other_requests_are_not_taken_for_pc_commands(query):
    decision, _ = await CoreOrchestrator().decide(query)
    assert decision.intent != Intent.PC_REMOTE.value


def test_configured_device_name_is_recognised(monkeypatch):
    class _Device:
        id = "pc_windows"
        name = "PC Windows"

    monkeypatch.setattr(
        "integrations.pc_remote.config.load_devices", lambda: {"pc_windows": _Device()}
    )
    assert orch._detect_pc_remote_action("lance notepad sur pc windows")
    assert not orch._detect_pc_remote_action("pc windows")  # pas de verbe d'action


def test_unreadable_registry_never_raises(monkeypatch):
    def broken():
        raise RuntimeError("neron.yaml illisible")

    monkeypatch.setattr("integrations.pc_remote.config.load_devices", broken)
    assert orch._detect_pc_remote_action("lance notepad sur pc windows") is False


async def test_agent_router_dispatches_to_pc_remote_agent(monkeypatch):
    from core.pipeline.routing import agent_router as ar

    calls = []

    class _Agent:
        async def execute(self, query):
            calls.append(query)
            return {"response": "htop lancé sur Serveur Ubuntu."}

    monkeypatch.setattr(ar, "_get_pc_remote", lambda: _Agent())
    monkeypatch.setattr(ar, "_result_to_text", lambda result: result["response"])
    intent_result = ar.IntentResult(intent=Intent.PC_REMOTE, confidence="high")
    text = await ar.AgentRouter().route(intent_result, "ouvre htop sur mon pc distant")
    assert calls == ["ouvre htop sur mon pc distant"]
    assert text == "htop lancé sur Serveur Ubuntu."
