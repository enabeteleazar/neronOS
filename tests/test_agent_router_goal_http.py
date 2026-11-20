"""Gestion des agents générés par la conversation : Core -> HTTP -> Goal.

Le registre et les fichiers d'agents vivent sur la machine de Goal. Lire
DynamicAgentRegistry ou appeler AgentManager / AgentBuildOrchestrator dans le
processus du Core donnait un état faux dès que les deux tournent sur des
serveurs distincts.
"""

from __future__ import annotations

import pytest

from core.pipeline.routing import agent_router as ar


class _Goal:
    def __init__(self, *, error=None):
        self.error = error
        self.calls: list[tuple] = []

    async def _call(self, *call, answer):
        self.calls.append(call)
        if self.error:
            raise self.error
        return answer

    async def list_agents(self):
        return await self._call("list", answer={"count": 2, "agents": ["veille_agent", "backup_agent"],
                                                 "disabled": ["backup_agent"]})

    async def scan_agents(self):
        return await self._call("scan", answer={"scanned": 3, "active": 2, "invalid": 1,
                                                 "runtime_reload": {"ok": True}})

    async def agent_registry_index(self):
        return await self._call("index", answer={"agents": {
            "a": {"agent_name": "veille_agent", "status": "active"},
            "b": {"agent_name": "casse_agent", "status": "invalid", "error": "SyntaxError"},
        }})

    async def update_agent(self, name, request):
        return await self._call("update", name, request, answer={
            "status": "updated", "agent": name, "test_result": {"returncode": 0},
            "runtime_reload": {"ok": True},
        })

    async def build_agent(self, query, **kwargs):
        return await self._call("build", query, kwargs["source_channel"],
                                answer={"response": "Agent veille_agent construit et validé."})


@pytest.fixture
def goal(monkeypatch):
    def install(**kwargs):
        fake = _Goal(**kwargs)
        monkeypatch.setattr("server.common.goal_client.get_goal_client", lambda: fake)
        return fake

    return install


async def test_list_comes_from_goal_with_disabled_state(goal):
    fake = goal()
    text = await ar._list_dynamic_agents()
    assert fake.calls == [("list",)]
    assert "- backup_agent (désactivé)" in text and "- veille_agent" in text


async def test_scan_index_and_invalid(goal):
    goal()
    assert "Invalides : 1." in await ar._scan_agent_registry_text()
    assert "veille_agent | active" in await ar._agent_registry_index_text()
    invalid = await ar._invalid_agent_registry_text()
    assert "casse_agent | SyntaxError" in invalid and "veille_agent" not in invalid


async def test_update_and_build_are_delegated(goal):
    fake = goal()
    text = await ar._update_dynamic_agent("ameliore agent veille_agent ajoute un seuil de 90 %")
    assert fake.calls[0][:2] == ("update", "veille_agent")
    assert "Agent mis à jour : veille_agent." in text and "Tests : OK." in text

    assert await ar._build_tracked_agent("crée un agent de veille", source_channel="telegram") == (
        "Agent veille_agent construit et validé."
    )
    assert fake.calls[-1] == ("build", "crée un agent de veille", "telegram")


@pytest.mark.parametrize(
    "call",
    [
        lambda: ar._list_dynamic_agents(),
        lambda: ar._scan_agent_registry_text(),
        lambda: ar._agent_registry_index_text(),
        lambda: ar._invalid_agent_registry_text(),
        lambda: ar._update_dynamic_agent("ameliore agent veille_agent ajoute un seuil"),
        lambda: ar._build_tracked_agent("crée un agent de veille"),
    ],
)
async def test_unreachable_goal_is_explained(goal, call):
    from server.common.goal_client import GoalClientError

    goal(error=GoalClientError("refusé"))
    assert "Goal est injoignable" in await call()


def test_core_no_longer_reads_goal_factory_in_process():
    import inspect

    for name in ("_list_dynamic_agents", "_scan_agent_registry_text", "_agent_registry_records",
                 "_build_tracked_agent", "_update_dynamic_agent"):
        source = inspect.getsource(getattr(ar, name))
        assert "agents.factory" not in source and "agents.runtime" not in source, name
