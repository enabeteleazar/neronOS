from __future__ import annotations

import pytest

from core.a2a import A2AClient, AgentCard
from goal_engine import (
    AgentCreationRequest,
    AgentFactory,
    AgentRegistry,
    GoalEngine,
    GoalRequest,
)
from core.providers.models import ProviderRequest, ProviderResponse
from core.providers.registry import ProviderRegistry
from core.pipeline.orchestrator import CoreOrchestrator


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeMemoryProvider:
    name = "memory-test"
    type = "memory"
    status = "healthy"
    capabilities = ["remember", "recall", "search", "status"]

    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []

    async def health(self):
        return ProviderResponse(provider=self.name, action="health", status="healthy")

    async def execute(self, request: ProviderRequest):
        self.requests.append(request)
        return ProviderResponse(
            provider=self.name,
            action=request.action,
            status="healthy",
            result={"saved": True},
            trace_id=request.trace_id,
        )


def _registry_with_memory(provider: FakeMemoryProvider | None = None) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(provider or FakeMemoryProvider())
    return registry


async def test_goal_engine_analyze_extracts_capabilities():
    engine = GoalEngine(providers=_registry_with_memory(), a2a=A2AClient(), agents=AgentRegistry())

    analysis = await engine.analyze(
        GoalRequest(objective="Crée un agent capable de surveiller l’état de Néron.")
    )

    assert analysis.objective.startswith("Crée un agent")
    assert "agent_creation" in analysis.required_capabilities
    assert "monitoring" in analysis.required_capabilities
    assert analysis.llm_used is False


def test_agent_registry_register_list_and_find():
    registry = AgentRegistry()
    card = AgentCard(
        agent_id="watch-agent",
        name="Watch Agent",
        capabilities=["monitoring", "service_supervision"],
        status="available",
    )

    registry.register(card)

    assert registry.list() == [card]
    assert registry.find_by_capability("monitoring") == [card]
    assert registry.find_for_goal(
        type("Analysis", (), {"required_capabilities": ["monitoring"]})()
    ) == card
    assert registry.status()["available_count"] == 1


def test_agent_registry_loads_and_converts_runtime_agents():
    class RuntimeRegistry:
        def list_agent_records(self):
            return [{
                "module_name": "diagnostic_agent",
                "agent_name": "Diagnostic Agent",
                "path": "/tmp/diagnostic_agent.py",
                "spec": {
                    "description": "Vérifie la santé de Néron",
                    "capabilities": ["diagnostics", "monitoring"],
                    "tags": ["health", "neron"],
                },
            }]

    runtime = type("Runtime", (), {"registry": RuntimeRegistry()})()
    registry = AgentRegistry(runtime=runtime)

    cards = registry.load_existing_agents()

    assert cards[0].agent_id == "diagnostic_agent"
    assert cards[0].capabilities == ["diagnostics", "monitoring"]
    assert cards[0].tags == ["health", "neron"]
    assert cards[0].metadata["source"] == "agent_runtime"


def test_agent_registry_find_for_goal_uses_description_tags_and_keywords():
    runtime = type("Runtime", (), {
        "registry": type("Registry", (), {"list_agent_records": lambda self: []})()
    })()
    registry = AgentRegistry(runtime=runtime)
    card = AgentCard(
        agent_id="diagnostic",
        name="Diagnostic Agent",
        description="Vérifie l'état de Néron",
        tags=["health", "diagnostic"],
        capabilities=["diagnostics"],
        status="available",
    )
    registry.register(card)
    analysis = type("Analysis", (), {
        "objective": "Utilise un agent de diagnostic pour vérifier l’état de Néron.",
        "required_capabilities": ["monitoring"],
    })()

    assert registry.find_for_goal(analysis) == card


async def test_goal_engine_without_agent_returns_agent_creation_required():
    memory = FakeMemoryProvider()
    engine = GoalEngine(
        providers=_registry_with_memory(memory),
        a2a=A2AClient(),
        agents=AgentRegistry(),
    )

    result = await engine.execute(
        GoalRequest(objective="Crée un agent capable de surveiller l’état de Néron.")
    )

    assert result.goal_status == "agent_creation_required"
    assert result.agent_found is False
    assert result.agent_creation_required is True
    assert result.a2a_used is False
    assert result.llm_used is False
    assert result.memory_learned is True
    assert memory.requests[-1].action == "remember"
    assert result.agent_creation_plan is not None
    assert result.agent_creation_plan["spec"]["modules"]
    assert result.agent_creation_plan["spec"]["tests"]
    assert result.agent_creation_plan["files_created"] is False


async def test_agent_factory_creates_spec_and_modules():
    engine = GoalEngine(providers=_registry_with_memory(), agents=AgentRegistry())
    analysis = await engine.analyze(GoalRequest(objective="Crée un agent de monitoring."))
    factory = AgentFactory()

    plan = factory.create_plan(AgentCreationRequest(goal_analysis=analysis))

    assert plan.spec.name == "monitoring_agent"
    assert "monitoring" in plan.spec.capabilities
    assert {module.name for module in plan.spec.modules} >= {
        "agent_creation_module",
        "monitoring_module",
    }
    assert "a2a_task_execution" in plan.spec.tests
    assert plan.files_created is False


async def test_goal_engine_with_agent_prepares_a2a_execution():
    agents = AgentRegistry()
    card = AgentCard(
        agent_id="watch-agent",
        name="Watch Agent",
        capabilities=["monitoring", "service_supervision"],
        status="available",
    )
    agents.register(card)
    a2a = A2AClient([card])
    engine = GoalEngine(
        providers=_registry_with_memory(),
        a2a=a2a,
        agents=agents,
    )

    result = await engine.execute(
        GoalRequest(objective="Surveille l’état de Néron.")
    )

    assert result.goal_status == "completed"
    assert result.agent_found is True
    assert result.agent_creation_required is False
    assert result.a2a_used is True
    assert result.execution.a2a_response is not None
    assert result.execution.a2a_response.status == "accepted"
    assert result.verification.status == "verified"
    assert result.loop_iterations == 1


async def test_goal_engine_learn_is_non_blocking_without_memory_provider():
    engine = GoalEngine(providers=ProviderRegistry(), a2a=A2AClient(), agents=AgentRegistry())

    result = await engine.execute(GoalRequest(objective="Crée un agent de monitoring."))

    assert result.goal_status == "agent_creation_required"
    assert result.memory_learned is False


@pytest.mark.parametrize(
    "query",
    [
        "Qui es-tu ?",
        "Quelle heure est-il ?",
        "Recherche Phase 2",
        "Explique-moi en une phrase ce qu’est NéronOS.",
    ],
)
async def test_simple_intents_do_not_route_to_goal_engine(query: str):
    decision, _ = await CoreOrchestrator().decide(query)

    assert decision.selected_route != "goal_engine"
