"""Gestion des agents par conversation : Core -> HTTP -> Goal.

Remplace 9f4e3e6 / e84fb0b / 3a56831 (perdus avec 58ab382), qui modifiaient
un registre en mémoire du Core (perdu au redémarrage, écrasé au rechargement,
sans effet sur l'exécution) et effaçaient des fichiers sur le disque de Goal.
Désormais :

- l'état activé/désactivé est persistant, à côté des agents
  (agents/factory/agent_state.py) ;
- le runtime refuse d'exécuter un agent désactivé, goal_engine ne le
  sélectionne plus ;
- le Core ne parle à Goal qu'en HTTP (POST /agents/{nom}/enable|disable|delete).
"""

from __future__ import annotations

import json

import pytest

from agents.factory import agent_state
from agents.factory.agent_manager import AgentManager
from core.pipeline import orchestrator as orch
from core.pipeline.intent.intent_router import Intent
from core.pipeline.orchestrator import CoreOrchestrator


# ── État persistant ─────────────────────────────────────────────────────────


def test_state_roundtrip_and_survives_a_new_reader(tmp_path):
    assert agent_state.disabled_agents(tmp_path) == set()
    agent_state.set_enabled(tmp_path, "veille_agent", False)
    agent_state.set_enabled(tmp_path, "autre_agent", False)
    agent_state.set_enabled(tmp_path, "autre_agent", True)
    # Relu depuis le disque : pas d'état en mémoire.
    assert agent_state.disabled_agents(tmp_path) == {"veille_agent"}
    assert json.loads(agent_state.state_path(tmp_path).read_text())["disabled"] == ["veille_agent"]
    assert not list(tmp_path.glob(".agents_state.*.tmp"))


def test_unreadable_state_disables_nothing(tmp_path):
    agent_state.state_path(tmp_path).write_text("{pas du json", encoding="utf-8")
    assert agent_state.disabled_agents(tmp_path) == set()


# ── AgentManager (côté Goal) ────────────────────────────────────────────────


@pytest.fixture
def manager(tmp_path):
    (tmp_path / "veille_agent.py").write_text("class Agent: ...\n", encoding="utf-8")
    (tmp_path / "meteo_agent.py").write_text("class Agent: ...\n", encoding="utf-8")
    return AgentManager(
        generated_agents=tmp_path,
        workspace_agents=tmp_path / "ws",
        workspace_tests=tmp_path / "wt",
        backups_dir=tmp_path / "bk",
        runtime_manager=object(),
    )


def test_manager_disables_then_enables(manager, tmp_path):
    assert manager.set_agent_enabled("veille_agent", False) == {
        "status": "disabled", "agent": "veille_agent", "enabled": False,
    }
    assert agent_state.is_disabled(tmp_path, "veille_agent")
    assert manager.set_agent_enabled("veille_agent", True)["status"] == "enabled"
    assert not agent_state.is_disabled(tmp_path, "veille_agent")


def test_manager_refuses_protected_and_unknown_agents(manager, tmp_path):
    assert manager.set_agent_enabled("meteo_agent", False)["status"] == "refused"
    assert manager.set_agent_enabled("fantome_agent", False)["status"] == "not_found"
    assert agent_state.disabled_agents(tmp_path) == set()


# ── Effet réel : exécution et sélection ─────────────────────────────────────


class _Registry:
    def __init__(self, generated_dir):
        self.generated_dir = generated_dir
        self._records = {"veille_agent": {"path": str(generated_dir / "veille_agent.py"), "spec": {}}}

    def load_generated_agents(self):
        return dict(self._records)

    def list_agent_records(self):
        return [{"module_name": "veille_agent", "agent_name": "veille_agent", "spec": {}}]


def test_runtime_refuses_a_disabled_agent(tmp_path):
    from agents.runtime.runtime import AgentDisabledError, AgentRuntime

    runtime = AgentRuntime(registry=_Registry(tmp_path), tool_registry=object(), tool_runtime=object())
    runtime.load_agent("veille_agent")  # actif : chargé
    agent_state.set_enabled(tmp_path, "veille_agent", False)
    with pytest.raises(AgentDisabledError, match="agent_disabled:veille_agent"):
        runtime.load_agent("veille_agent")


def test_goal_engine_no_longer_selects_a_disabled_agent(tmp_path):
    from goal_engine.agent_registry import AgentRegistry

    agent_state.set_enabled(tmp_path, "veille_agent", False)
    registry = AgentRegistry()
    registry.load_existing_agents(runtime=_Registry(tmp_path))
    assert registry.get("veille_agent").status == "unavailable"


# ── Core : reconnaissance des commandes ─────────────────────────────────────


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Désactive l'agent veille_agent", ("disable", "veille_agent")),
        ("arrête l’agent veille-agent", ("disable", "veille-agent")),
        ("Stoppe agent veille_agent.", ("disable", "veille_agent")),
        ("Réactive l'agent veille_agent", ("enable", "veille_agent")),
        ("Supprime l'agent veille_agent", ("delete", "veille_agent")),
        ("Efface agent veille_agent", ("delete", "veille_agent")),
        ("Confirme la suppression de l'agent veille_agent", ("delete_confirm", "veille_agent")),
    ],
)
def test_agent_commands_are_parsed(query, expected):
    assert orch._parse_agent_admin(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "Active la lumière du salon",          # capté en septembre
        "Supprime l'alarme de demain",         # idem
        "Désactive le chauffage",
        "Active agent veille_agent",           # promotion : sens existant conservé
        "Arrête de parler",
    ],
)
def test_other_phrases_are_not_agent_commands(query):
    assert orch._parse_agent_admin(query) is None


async def test_promotion_keeps_its_route():
    decision, _ = await CoreOrchestrator().decide("active agent veille_agent")
    assert decision.selected_route == "agent_manager"


# ── Core : exécution via Goal (HTTP) ────────────────────────────────────────


class _FakeGoal:
    def __init__(self, answer=None, error=None):
        self.calls: list[tuple] = []
        self.answer = answer
        self.error = error

    async def _reply(self, call, default):
        self.calls.append(call)
        if self.error:
            raise self.error
        return self.answer or default

    async def set_agent_enabled(self, name, enabled):
        status = "enabled" if enabled else "disabled"
        return await self._reply(("enabled", name, enabled), {"status": status, "agent": name})

    async def delete_agent(self, name):
        return await self._reply(
            ("delete", name),
            {"status": "deleted", "agent": name, "backup": {"backup_path": "/sauvegardes/veille_agent.py"}},
        )


@pytest.fixture
def goal(monkeypatch):
    def install(**kwargs):
        fake = _FakeGoal(**kwargs)
        monkeypatch.setattr("server.common.goal_client.get_goal_client", lambda: fake)
        return fake

    return install


async def test_disable_goes_through_goal(goal):
    fake = goal()
    result = await CoreOrchestrator().handle("Désactive l'agent veille_agent")
    assert result.decision.selected_route == "agent_admin"
    assert result.decision.intent == Intent.AGENT_DISABLE.value
    assert fake.calls == [("enabled", "veille_agent", False)]
    assert "désactivé" in result.response and "réactive l'agent veille_agent" in result.response


async def test_delete_asks_confirmation_before_calling_goal(goal):
    fake = goal()
    first = await CoreOrchestrator().handle("Supprime l'agent veille_agent")
    assert fake.calls == []
    assert "confirme la suppression de l'agent veille_agent" in first.response

    second = await CoreOrchestrator().handle("Confirme la suppression de l'agent veille_agent")
    assert fake.calls == [("delete", "veille_agent")]
    assert "supprimé" in second.response and "/sauvegardes/veille_agent.py" in second.response


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ({"status": "not_found", "agent": "x_agent"}, "introuvable"),
        ({"status": "refused", "agent": "meteo_agent"}, "protégé"),
    ],
)
async def test_goal_refusals_are_explained(goal, answer, expected):
    goal(answer=answer)
    result = await CoreOrchestrator().handle("Désactive l'agent x_agent")
    assert expected in result.response


async def test_unreachable_goal_is_reported(goal):
    from server.common.goal_client import GoalClientError

    goal(error=GoalClientError("Erreur réseau appelant goal"))
    result = await CoreOrchestrator().handle("Réactive l'agent veille_agent")
    assert "injoignable" in result.response
    assert result.error
