from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.capabilities.decision_engine import DecisionEngine
from modules.capabilities.models import CapabilityRequest
from modules.capabilities.registry import CapabilityRegistry
from modules.capabilities.resolver import CapabilityResolver


class EmptyAgentRegistry:
    def list_agent_records(self):
        return []


class EmptyProjectManager:
    def list_projects(self, status=None, limit=100):
        return []


def _registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        agent_registry=EmptyAgentRegistry(),
        project_manager=EmptyProjectManager(),
        builtins=[],
    )


def _connector(connector_id: str, name: str, connect_hint: str = "Connecte-toi ici."):
    return SimpleNamespace(id=connector_id, name=name, connect_hint=connect_hint)


def _state(status: str):
    return SimpleNamespace(status=status)


def _resolver(gateway_lookup) -> CapabilityResolver:
    return CapabilityResolver(
        registry=_registry(),
        decision_engine=DecisionEngine(gateway_lookup=gateway_lookup),
    )


@pytest.mark.asyncio
async def test_connected_gateway_response_mentions_the_connector(monkeypatch):
    def lookup(domain: str):
        return [(_connector("google", "Google"), _state("connected"))]

    monkeypatch.setattr(
        "gateways.registry.get_registry",
        lambda: SimpleNamespace(get=lambda cid: _connector("google", "Google")),
    )

    resolver = _resolver(lookup)
    result = await resolver.resolve(CapabilityRequest(text="Montre mes mails"))

    assert result is not None
    assert result.status == "completed"
    assert "Google" in result.response
    assert result.decision.decision == "use_gateway"
    assert result.decision.gateway_connector_id == "google"


@pytest.mark.asyncio
async def test_disconnected_gateway_proposes_connection_with_hint(monkeypatch):
    def lookup(domain: str):
        return [(_connector("github", "GitHub", "Genere un token."), _state("configured_disconnected"))]

    monkeypatch.setattr(
        "gateways.registry.get_registry",
        lambda: SimpleNamespace(
            get=lambda cid: _connector("github", "GitHub", "Genere un token.")
        ),
    )

    resolver = _resolver(lookup)
    result = await resolver.resolve(CapabilityRequest(text="Montre la pull request"))

    assert result is not None
    assert result.status == "action_required"
    assert "GitHub" in result.response
    assert "Genere un token." in result.response
    assert result.decision.decision == "propose_gateway_connection"


@pytest.mark.asyncio
async def test_no_gateway_available_says_so_without_creating_an_agent():
    def lookup(domain: str):
        return []

    resolver = _resolver(lookup)
    result = await resolver.resolve(CapabilityRequest(text="Montre mes notes"))

    assert result is not None
    assert result.status == "completed"
    assert "pas encore de passerelle" in result.response
    assert result.decision.decision == "no_gateway_available"
