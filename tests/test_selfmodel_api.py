from __future__ import annotations

import httpx
import pytest

from core import app as core_app
from core.providers import ensure_default_providers, provider_registry


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_selfmodel_sensitive_endpoints_remain_protected(monkeypatch):
    monkeypatch.setattr(core_app.settings, "API_KEY", "selfmodel-test-key")
    transport = httpx.ASGITransport(app=core_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/selfmodel/status")

    assert response.status_code == 401


async def test_selfmodel_exposes_internal_truth_sources(monkeypatch):
    ensure_default_providers()
    monkeypatch.setattr(core_app.settings, "API_KEY", "selfmodel-test-key")
    transport = httpx.ASGITransport(app=core_app.app)
    headers = {"Authorization": "Bearer selfmodel-test-key"}
    paths = (
        "status",
        "identity",
        "capabilities",
        "providers",
        "registered-services",
        "agents",
        "memory",
        "goals",
        "architecture",
    )

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=headers,
    ) as client:
        responses = {path: await client.get(f"/selfmodel/{path}") for path in paths}

    assert all(response.status_code == 200 for response in responses.values())
    assert responses["identity"].json()["name"] == "Néron"
    assert "capabilities" in responses["capabilities"].json()
    assert "providers" in responses["providers"].json()
    assert responses["registered-services"].json()["source"] == "service_registry"
    assert "agents" in responses["agents"].json()
    assert "provider" in responses["memory"].json()
    assert "goals" in responses["goals"].json()
    assert responses["architecture"].json()["self_awareness"] == "self_model"


async def test_pc_remote_agent_is_a2a_agent_and_never_a_provider(monkeypatch):
    ensure_default_providers()
    monkeypatch.setattr(core_app.settings, "API_KEY", "selfmodel-test-key")
    transport = httpx.ASGITransport(app=core_app.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer selfmodel-test-key"},
    ) as client:
        providers = (await client.get("/selfmodel/providers")).json()
        agents = (await client.get("/selfmodel/agents")).json()

    assert "pc_remote_agent" not in {item["id"] for item in providers["providers"]}
    provider_names = {item["id"] for item in providers["providers"]}
    agent_ids = {item["id"] for item in agents["agents"]}
    assert "pc_remote_agent" in agent_ids
    assert provider_names.isdisjoint(agent_ids)
    assert all(
        item["type"] in {"llm", "memory", "homeassistant", "goal", "doctor"}
        and item["status"] in {"online", "offline", "degraded", "unknown"}
        for item in providers["providers"]
    )
    assert all(
        item["status"] in {"online", "offline", "degraded", "unknown"}
        and item["current_task"] is None
        for item in agents["agents"]
    )
    pc_remote_agent = next(item for item in agents["agents"] if item["id"] == "pc_remote_agent")
    assert pc_remote_agent["metadata"]["capabilities"]
    assert provider_registry.get("pc_remote_agent") is None


async def test_selfmodel_architecture_documents_strict_separation(monkeypatch):
    monkeypatch.setattr(core_app.settings, "API_KEY", "selfmodel-test-key")
    transport = httpx.ASGITransport(app=core_app.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer selfmodel-test-key"},
    ) as client:
        architecture = (await client.get("/selfmodel/architecture")).json()

    assert architecture["separation"]["providers"]["kind"] == "provider"
    assert architecture["separation"]["agents"]["kind"] == "agent"
    assert architecture["separation"]["agents"]["developed_by"] == "goal_engine"
    assert architecture["separation"]["agents"]["future_manager"] == "provider_agent"


async def test_existing_status_route_remains_available(monkeypatch):
    monkeypatch.setattr(core_app.settings, "API_KEY", "selfmodel-test-key")
    transport = httpx.ASGITransport(app=core_app.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer selfmodel-test-key"},
    ) as client:
        response = await client.get("/status")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
