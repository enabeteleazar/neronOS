"""SelfModel rétabli (5d2ba02, 220ff53, 2e0ad2b…, perdus avec 58ab382) et
adapté aux modules sur des serveurs physiques distincts.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.modules.status import services_snapshot as svc
from core.modules.self_model.homelab import node_base_url


# ── Services : systemd local + registry ─────────────────────────────────────


@pytest.fixture
def registry(monkeypatch):
    def install(entries, units):
        monkeypatch.setattr(svc, "_cache", None)
        monkeypatch.setattr(svc, "_discover", lambda: units)
        monkeypatch.setattr(svc, "_show", lambda u: {})
        monkeypatch.setattr(
            svc, "_registry_index", lambda: {e["service_name"]: e for e in entries}
        )

    return install


def _states(snapshot):
    return {row["key"]: row["state"] for row in snapshot["units"]}


def test_service_on_another_machine_is_remote_not_orphan(registry):
    registry(
        [
            {"service_name": "core", "host": "127.0.1.1"},
            {"service_name": "llm", "host": "100.90.194.20"},      # autre serveur
            {"service_name": "memory", "host": "127.0.1.4"},       # local sans unité
            {"service_name": "homeassistant", "host": "100.90.194.30"},
        ],
        ["neron@core.service"],
    )
    snapshot = svc.services_snapshot()
    assert _states(snapshot) == {
        "core": "ok",
        "llm": "remote",
        "memory": "orphan",
        "homeassistant": "foreign",
    }
    groups = {row["key"]: row["group"] for row in snapshot["units"]}
    # Service Néron distant : liste principale du Dashboard, pas « externe ».
    assert groups["llm"] == "applicatif"
    assert groups["homeassistant"] == "externe"


def test_registry_view_survives_without_systemctl(registry):
    registry([{"service_name": "llm", "host": "100.90.194.20"}], None)
    snapshot = svc.services_snapshot()
    assert snapshot["available"] is True
    assert snapshot["systemd_available"] is False
    assert _states(snapshot) == {"llm": "remote"}


def test_nothing_at_all_is_reported_unavailable(registry):
    registry([], None)
    assert svc.services_snapshot()["available"] is False


# ── Adresses des nœuds : neron.server.yaml ──────────────────────────────────


def test_node_url_follows_server_yaml(monkeypatch, tmp_path, request):
    from core.modules.self_model import homelab

    # Chemin du YAML mis en cache au premier appel (stable en production) :
    # on le vide pour que NERON_SERVER_CONFIG soit relu, avant et après.
    homelab._server_config_path.cache_clear()
    request.addfinalizer(homelab._server_config_path.cache_clear)
    plan = tmp_path / "neron.server.yaml"
    plan.write_text(
        "nodes:\n"
        "  doctor: {host: 192.168.1.50, port: 8060}\n"
        "  voice: {host: 192.168.1.60, stt_port: 8045, ui_port: 8082}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NERON_SERVER_CONFIG", str(plan))
    assert node_base_url("doctor", "http://127.0.1.9:8060") == "http://192.168.1.50:8060"
    assert node_base_url("voice", "x") == "http://192.168.1.60:8045"
    assert node_base_url("print", "http://127.0.1.7:8050") == "http://127.0.1.7:8050"


# ── Routes /self-model ──────────────────────────────────────────────────────


class _Goal:
    def __init__(self, *, error=None, enabled_answer=None):
        self.error = error
        self.enabled_answer = enabled_answer
        self.calls = []

    async def _maybe_fail(self):
        if self.error:
            raise self.error

    async def list_agents(self):
        await self._maybe_fail()
        return {"count": 2, "agents": ["veille_agent", "backup_agent"], "disabled": ["backup_agent"]}

    async def set_agent_enabled(self, name, enabled):
        self.calls.append((name, enabled))
        await self._maybe_fail()
        return self.enabled_answer or {
            "status": "enabled" if enabled else "disabled", "agent": name, "enabled": enabled,
        }

    async def get_task_summary(self):
        await self._maybe_fail()
        return {"total": 3, "pending": 1}

    async def get_next_task(self):
        await self._maybe_fail()
        return {"id": "t1"}


@pytest.fixture
def client(monkeypatch):
    from core.api import self_model_routes

    snapshot = {
        "agent_topology": {"count": 1, "agents": [{"agent_id": "a2a_weather", "status": "available"}]},
        "agents": {"source": "a2a_only"},
        "a2a": {},
        "tasks": {"summary": None},
        "goal": {},
    }
    monkeypatch.setattr(self_model_routes, "_snapshot_sync", lambda: snapshot)

    def install(goal: _Goal):
        monkeypatch.setattr("server.common.goal_client.get_goal_client", lambda: goal)
        app = FastAPI()
        app.include_router(self_model_routes.router)
        return TestClient(app)

    return install


def test_agents_panel_lists_goal_agents_with_their_state(client):
    data = client(_Goal()).get("/self-model/agents").json()
    states = {a["agent_id"]: a["status"] for a in data["agents"]}
    assert states == {"a2a_weather": "available", "veille_agent": "available", "backup_agent": "unavailable"}
    assert data["goal"]["reachable"] is True


def test_agents_panel_still_answers_when_goal_is_down(client):
    from server.common.goal_client import GoalClientError

    data = client(_Goal(error=GoalClientError("down"))).get("/self-model/agents").json()
    assert [a["agent_id"] for a in data["agents"]] == ["a2a_weather"]
    assert data["goal"]["reachable"] is False


def test_dashboard_toggle_goes_through_goal(client):
    goal = _Goal()
    response = client(goal).post("/self-model/agents/backup_agent/status", json={"enabled": True})
    assert response.status_code == 200
    assert response.json() == {"agent_id": "backup_agent", "status": "available"}
    assert goal.calls == [("backup_agent", True)]


@pytest.mark.parametrize(
    ("answer", "error", "code"),
    [
        ({"status": "not_found", "agent": "x"}, None, 404),
        ({"status": "refused", "agent": "meteo_agent"}, None, 403),
        (None, "down", 503),
    ],
)
def test_dashboard_toggle_errors(client, answer, error, code):
    from server.common.goal_client import GoalClientError

    goal = _Goal(enabled_answer=answer, error=GoalClientError(error) if error else None)
    response = client(goal).post("/self-model/agents/x/status", json={"enabled": False})
    assert response.status_code == code


def test_context_reads_identity_and_goal_tasks_over_http(client):
    data = client(_Goal()).get("/self-model/context").json()
    assert data["identity"]["name"]
    assert data["tasks"]["summary"] == {"total": 3, "pending": 1}
    assert data["tasks"]["source"] == "goal_http"


def test_self_model_package_never_imports_goal():
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "core"
    sources = [*root.joinpath("modules", "self_model").glob("*.py"), root / "api" / "self_model_routes.py"]
    offenders = [
        str(path.name)
        for path in sources
        if re.search(r"^\s*(from|import)\s+(goal\b|core\.goal_engine)", path.read_text(encoding="utf-8"), re.M)
    ]
    assert offenders == []
