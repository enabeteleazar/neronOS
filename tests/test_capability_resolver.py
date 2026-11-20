from __future__ import annotations

from modules.capabilities.models import Capability, CapabilityRequest
from modules.capabilities.registry import CapabilityRegistry
from modules.capabilities.resolver import (
    ASYNC_AGENT_RESPONSE,
    ASYNC_RESPONSE,
    CapabilityResolver,
)


class EmptyAgentRegistry:
    def list_agent_records(self):
        return []


class StaticAgentRegistry:
    def __init__(self, records):
        self.records = records

    def list_agent_records(self):
        return self.records


class EmptyProjectManager:
    def list_projects(self, status=None, limit=100):
        return []


class FakeRuntime:
    def __init__(self, response: str = "agent response") -> None:
        self.response = response
        self.calls = []

    async def run(self, name: str, text: str):
        self.calls.append((name, text))
        return {"ok": True, "agent": name, "response": self.response}


class FakeGoalManager:
    def __init__(self) -> None:
        self.created = []
        self.updated = []

    def create_goal(self, **kwargs):
        self.created.append(kwargs)
        return {"id": "goal-capability-1", "metadata": kwargs.get("metadata", {})}

    def update_status(self, goal_id, status, **kwargs):
        self.updated.append((goal_id, status, kwargs))
        return {"id": goal_id, "status": status}


class FakeExecutionEngine:
    def __init__(self) -> None:
        self.enqueued = []
        self.status = {"goal_id": "goal-capability-1", "status": "queued"}

    def enqueue_goal(self, goal_id, title, source, metadata):
        self.enqueued.append((goal_id, title, source, metadata))
        return self.status

    def get_goal_status(self, goal_id):
        return self.status


class FakeBackgroundRunner:
    def __init__(self) -> None:
        self.submitted = []

    def submit(self, **kwargs):
        self.submitted.append(kwargs)


class FakeTaskScheduler:
    def __init__(self) -> None:
        self.chains = []

    def enqueue_tool_chain(self, tool_slugs, **kwargs):
        self.chains.append((tool_slugs, kwargs))
        return [
            type("Task", (), {"task_id": f"task-{position}"})()
            for position, _slug in enumerate(tool_slugs)
        ]

    def enqueue_composite_task(self, **kwargs):
        return type("Task", (), {"task_id": "task-composite"})()

    def wake_worker(self):
        return None


def make_registry(*capabilities: Capability) -> CapabilityRegistry:
    return CapabilityRegistry(
        agent_registry=EmptyAgentRegistry(),
        project_manager=EmptyProjectManager(),
        builtins=capabilities,
    )


async def test_simple_easter_request_uses_existing_tool():
    resolver = CapabilityResolver(
        registry=CapabilityRegistry(
            agent_registry=EmptyAgentRegistry(),
            project_manager=EmptyProjectManager(),
        )
    )

    request = CapabilityRequest(text="Donne-moi la date de Pâques 2027")
    decision = resolver.decide(request)
    result = await resolver.resolve(request)

    assert decision is not None
    assert decision.decision == "use_existing_tool"
    assert decision.selected_tool == "date.easter"
    assert result is not None
    assert result.response == "Pâques 2027 tombe le 28 mars 2027."


async def test_current_date_request_uses_existing_tool():
    resolver = CapabilityResolver(
        registry=CapabilityRegistry(
            agent_registry=EmptyAgentRegistry(),
            project_manager=EmptyProjectManager(),
        )
    )

    decision = resolver.decide(CapabilityRequest(text="Donne-moi la date"))

    assert decision is not None
    assert decision.decision == "use_existing_tool"
    assert decision.selected_tool == "date.current"


async def test_unknown_simple_request_queues_tool_creation():
    goals = FakeGoalManager()
    engine = FakeExecutionEngine()
    runner = FakeBackgroundRunner()
    resolver = CapabilityResolver(
        registry=make_registry(),
        goal_manager=goals,
        execution_engine=engine,
        background_runner=runner,
    )

    result = await resolver.resolve(
        CapabilityRequest(
            text="Convertis ce nombre dans un format propriétaire",
            channel="telegram",
            user_id="chat-1",
        )
    )

    assert result is not None
    assert result.status == "pending"
    assert result.async_started is True
    assert result.response == ASYNC_RESPONSE
    assert result.decision is not None
    assert result.decision.decision == "create_tool"
    assert goals.created[0]["metadata"]["creation_type"] == "tool"
    assert runner.submitted[0]["goal_id"] == "goal-capability-1"


async def test_durable_request_queues_agent_creation():
    goals = FakeGoalManager()
    engine = FakeExecutionEngine()
    runner = FakeBackgroundRunner()
    resolver = CapabilityResolver(
        registry=make_registry(),
        goal_manager=goals,
        execution_engine=engine,
        background_runner=runner,
    )

    result = await resolver.resolve(
        CapabilityRequest(text="Surveille mon serveur et préviens-moi si le disque dépasse 85 %")
    )

    assert result is not None
    assert result.decision is not None
    assert result.decision.decision == "create_agent"
    assert result.async_started is True
    assert result.goal_id == "goal-capability-1"
    assert goals.created[0]["metadata"]["creation_type"] == "agent"
    assert goals.created[0]["metadata"]["internal_capability_request"] is True


async def test_unknown_automatic_log_analysis_queues_agent_creation():
    goals = FakeGoalManager()
    engine = FakeExecutionEngine()
    runner = FakeBackgroundRunner()
    scheduler = FakeTaskScheduler()
    resolver = CapabilityResolver(
        registry=make_registry(),
        goal_manager=goals,
        execution_engine=engine,
        background_runner=runner,
        task_scheduler=scheduler,
    )

    result = await resolver.resolve(
        CapabilityRequest(
            text="Analyse automatiquement les logs Néron et résume les erreurs critiques",
            channel="telegram",
        )
    )

    assert result is not None
    assert result.decision is not None
    assert result.decision.decision == "create_agent"
    assert result.async_started is True
    assert result.goal_id == "goal-capability-1"
    assert result.response == ASYNC_AGENT_RESPONSE
    assert engine.enqueued[0][3]["internal_capability_request"] is True
    assert len(engine.enqueued[0][3]["scheduler_task_ids"]) == 3
    assert engine.enqueued[0][3]["task_id"] == "task-0"
    assert engine.enqueued[0][3]["composite_task_id"] == "task-composite"


async def test_unknown_punctual_analysis_queues_tool_creation():
    goals = FakeGoalManager()
    engine = FakeExecutionEngine()
    runner = FakeBackgroundRunner()
    resolver = CapabilityResolver(
        registry=make_registry(),
        goal_manager=goals,
        execution_engine=engine,
        background_runner=runner,
    )

    result = await resolver.resolve(
        CapabilityRequest(
            text="Analyse ces logs et résume les erreurs critiques",
            channel="telegram",
        )
    )

    assert result is not None
    assert result.decision is not None
    assert result.decision.decision == "create_tool"
    assert result.async_started is True
    assert result.goal_id == "goal-capability-1"
    assert goals.created[0]["metadata"]["creation_type"] == "tool"


async def test_existing_durable_agent_is_executed():
    runtime = FakeRuntime("Je surveille déjà ce serveur.")
    capability = Capability(
        slug="server_watch_agent",
        name="Surveillance serveur",
        capability_type="agent",
        source="runtime_agent",
        description="Surveille un serveur et déclenche une alerte disque.",
        aliases=["surveille mon serveur"],
        agent_slug="server_watch_agent",
    )
    resolver = CapabilityResolver(
        registry=make_registry(capability),
        runtime_manager=runtime,
    )

    result = await resolver.resolve(CapabilityRequest(text="Surveille mon serveur"))

    assert result is not None
    assert result.decision is not None
    assert result.decision.decision == "use_existing_agent"
    assert result.response == "Je surveille déjà ce serveur."
    assert runtime.calls == [("server_watch_agent", "Surveille mon serveur")]


async def test_existing_generated_tool_is_executed_through_runtime():
    runtime = FakeRuntime("Résultat déterministe.")
    capability = Capability(
        slug="custom_date_tool",
        name="Date spéciale",
        capability_type="tool",
        source="generated_tool",
        description="Donne une date spéciale.",
        aliases=["date spéciale"],
        tool_slug="custom_date_tool",
        agent_slug="custom_date_tool",
    )
    resolver = CapabilityResolver(
        registry=make_registry(capability),
        runtime_manager=runtime,
    )

    result = await resolver.resolve(CapabilityRequest(text="Donne la date spéciale"))

    assert result is not None
    assert result.decision is not None
    assert result.decision.decision == "use_existing_tool"
    assert result.tool_slug == "custom_date_tool"
    assert runtime.calls == [("custom_date_tool", "Donne la date spéciale")]


async def test_dangerous_request_requires_human_validation():
    resolver = CapabilityResolver(registry=make_registry())

    result = await resolver.resolve(
        CapabilityRequest(text="Supprime tous les fichiers et désactive la sécurité")
    )

    assert result is not None
    assert result.status == "validation_required"
    assert result.decision is not None
    assert result.decision.decision == "ask_human_validation"
    assert result.decision.human_validation_required is True


def test_historical_generic_internal_agent_is_not_routable():
    registry = CapabilityRegistry(
        agent_registry=StaticAgentRegistry(
            [
                {
                    "module_name": "durable_repond_a_agent",
                    "agent_name": "durable_repond_a_agent",
                    "match_text": (
                        "analyse automatiquement les logs neron "
                        "resume les erreurs critiques"
                    ),
                    "spec": {
                        "kind": "agent",
                        "goal": "Analyser automatiquement les logs Néron",
                    },
                    "spec_signature": "generic-log-agent",
                }
            ]
        ),
        project_manager=type(
            "Projects",
            (),
            {
                "list_projects": lambda self, status=None, limit=100: [
                    {
                        "status": "completed",
                        "registered_agent": "durable_repond_a_agent",
                        "metadata": {
                            "agent_name": "durable_repond_a_agent",
                            "capability_request_id": "cap-old",
                            "creation_type": "agent",
                        },
                        "business_validation_result": {
                            "ok": True,
                            "scenario": {
                                "name": "generic_non_empty_response",
                                "fallback": True,
                            },
                            "actual_response": "Demande traitée : Analyse les logs Néron",
                        },
                    }
                ]
            },
        )(),
        builtins=[],
    )
    resolver = CapabilityResolver(registry=registry)

    decision = resolver.decide(
        CapabilityRequest(
            text="Analyse automatiquement les logs Néron et résume les erreurs critiques"
        )
    )

    assert decision is not None
    assert decision.decision == "create_agent"
