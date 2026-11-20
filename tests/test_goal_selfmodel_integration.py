from __future__ import annotations

import pytest

from core.a2a import A2AClient, AgentCard
from goal_engine import (
    AgentRegistry,
    GoalEngine,
    GoalRequest,
    SelfModelGoalContext,
)
from core.providers.registry import ProviderRegistry


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeSelfModelClient:
    def __init__(self, context: SelfModelGoalContext):
        self.context = context

    async def load(self) -> SelfModelGoalContext:
        return self.context


def _context(*, available=True, error=None):
    return SelfModelGoalContext(
        available=available,
        error=error,
        status={"health": {"global": "stable"}},
        capabilities={"available": ["weather", "generate", "remember"]},
        providers={
            "providers": [
                {"name": "oblivia", "capabilities": ["remember", "recall", "search"]},
                {"name": "llm", "capabilities": ["generate"]},
            ]
        },
        agents={
            "a2a": {
                "agents": [{
                    "agent_id": "open_meteo",
                    "status": "available",
                    "capabilities": ["weather", "forecast", "current_weather"],
                }]
            },
            "registry": {"agents": []},
        },
        memory={"provider": {"name": "oblivia"}, "status": "healthy"},
        architecture={"agents": "a2a_client"},
    )


async def test_goal_analysis_uses_selfmodel_to_select_a2a_agent():
    card = AgentCard(
        agent_id="open_meteo",
        name="Open-Meteo",
        capabilities=["weather", "forecast"],
        status="available",
    )
    engine = GoalEngine(
        providers=ProviderRegistry(),
        a2a=A2AClient([card]),
        agents=AgentRegistry(),
        selfmodel=FakeSelfModelClient(_context()),
    )

    analysis = await engine.analyze(GoalRequest(objective="Crée un agent météo."))
    selected = engine.find_agent(analysis)

    assert analysis.metadata["selfmodel_used"] is True
    assert analysis.metadata["selfmodel_available"] is True
    assert analysis.metadata["selected_agent_from_selfmodel"] == "open_meteo"
    assert analysis.metadata["selected_provider_from_selfmodel"] is None
    assert selected.agent_id == "open_meteo"


async def test_goal_analysis_selects_llm_provider_from_selfmodel():
    engine = GoalEngine(
        providers=ProviderRegistry(),
        a2a=A2AClient(),
        agents=AgentRegistry(),
        selfmodel=FakeSelfModelClient(_context()),
    )

    analysis = await engine.analyze(
        GoalRequest(objective="Rédige et explique une architecture distribuée.")
    )

    assert analysis.metadata["selected_provider_from_selfmodel"] == "llm"
    assert "Provider llm" in analysis.metadata["selfmodel_decision_reason"]


async def test_goal_selfmodel_fallback_is_explicit():
    engine = GoalEngine(
        providers=ProviderRegistry(),
        a2a=A2AClient(),
        agents=AgentRegistry(),
        selfmodel=FakeSelfModelClient(
            SelfModelGoalContext(available=False, error="selfmodel unavailable")
        ),
    )

    analysis = await engine.analyze(GoalRequest(objective="Construis un rapport complexe."))

    assert analysis.metadata["selfmodel_used"] is True
    assert analysis.metadata["selfmodel_available"] is False
    assert analysis.metadata["selfmodel_error"] == "selfmodel unavailable"
    assert "fallback" in analysis.metadata["selfmodel_decision_reason"].lower()


async def test_goal_does_not_bypass_available_selfmodel_agent_view():
    local_agents = AgentRegistry()
    local_agents.register(AgentCard(
        agent_id="hidden-local-agent",
        name="Hidden Local Agent",
        capabilities=["weather"],
        status="available",
    ))
    context = _context()
    context.agents = {"a2a": {"agents": []}, "registry": {"agents": []}}
    engine = GoalEngine(
        providers=ProviderRegistry(),
        a2a=A2AClient(),
        agents=local_agents,
        selfmodel=FakeSelfModelClient(context),
    )

    analysis = await engine.analyze(GoalRequest(objective="Météo actuelle à Paris"))

    assert engine.find_agent(analysis) is None
