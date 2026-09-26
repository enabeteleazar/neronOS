from __future__ import annotations

import pytest

from core.pipeline.orchestrator import CoreOrchestrator
from core.providers.registry import ProviderRegistry


EXPECTED_DECISION_KEYS = {
    "intent",
    "selected_route",
    "reason",
    "complexity",
    "requires_llm",
    "requires_timer",
    "requires_memory",
    "requires_knowledge",
    "requires_tool",
    "requires_resolver",
    "requires_agent_factory",
    "requires_goal_pipeline",
    "requires_governor",
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_route"),
    [
        # Les civilites sont repondues localement, sans modele de langage.
        ("Salut Neron", "smalltalk"),
        ("Explique-moi Kubernetes", "llm_provider"),
        ("Quelle est ta mission ?", "identity_provider"),
        ("Comment fonctionnes-tu ?", "identity_provider"),
        ("Quelle heure est-il ?", "timer_engine"),
        ("Mets un minuteur de 10 minutes", "timer_engine"),
        ("Souviens-toi de mon projet Neron", "memory_provider"),
        ("Cree un outil pour surveiller systemd", "goal_engine"),
        ("Analyse cette demande complexe", "goal_engine"),
        ("/goal cree un agent meteo", "goal_engine"),
        ("/help", "help_provider"),
        # Domaines externes portes par le registre de passerelles
        # (server/gateways) : doivent atteindre le resolver, jamais tomber
        # dans le chat LLM generique. Regression du 26/09/2026 — ces
        # domaines existaient deja dans modules.capabilities.rules mais
        # _requires_specialized_resolution ne les reconnaissait pas encore,
        # donc route="llm_provider" et une reponse hallucinee au lieu du
        # routage passerelle.
        ("Ouvre mon repo", "resolver"),
        ("Montre mes mails", "resolver"),
        ("Montre mes contacts", "resolver"),
        ("Montre mes notes", "resolver"),
        ("Montre mes rappels", "resolver"),
        ("Ouvre mon calendrier", "resolver"),
        ("Montre la pull request", "resolver"),
        ("Ouvre ma page Notion", "resolver"),
    ],
)
async def test_core_orchestrator_is_the_single_route_authority(
    query: str,
    expected_route: str,
):
    orchestrator = CoreOrchestrator()

    decision, _ = await orchestrator.decide(query)

    assert decision.selected_route == expected_route
    assert set(decision.to_dict()) == EXPECTED_DECISION_KEYS
    assert decision.reason
    assert decision.complexity in {"simple", "medium", "complex"}


class FakeAgentRouter:
    def __init__(self) -> None:
        self.calls = []

    async def route(self, intent_result, query, source_channel="api"):
        self.calls.append((intent_result.intent.value, query, source_channel))
        return "reponse llm"


class ForbiddenResolver:
    async def resolve(self, _request):
        raise AssertionError("Resolver must not run for ordinary conversation")


@pytest.mark.asyncio
async def test_orchestrator_does_not_route_everything_to_resolver(monkeypatch):
    monkeypatch.setattr(
        "core.pipeline.orchestrator.provider_registry",
        ProviderRegistry(),
    )
    agent_router = FakeAgentRouter()
    orchestrator = CoreOrchestrator(
        agent_router=agent_router,
        capability_resolver=ForbiddenResolver(),
    )

    result = await orchestrator.handle("Explique-moi Kubernetes")

    assert result.decision.selected_route == "llm_provider"
    assert result.executor == "llm"
    assert result.error == "llm provider unavailable"
    assert agent_router.calls == []


@pytest.mark.asyncio
async def test_help_returns_phase4_sections_without_obsolete_commands():
    class ForbiddenAgentRouter:
        async def route(self, *_args, **_kwargs):
            raise AssertionError("/help must not use the LLM/agent router")

    result = await CoreOrchestrator(agent_router=ForbiddenAgentRouter()).handle(
        "/help"
    )

    assert result.decision.selected_route == "help_provider"
    assert result.executor == "help_provider"
    for section in (
        "🤖 Néron — Commandes disponibles",
        "💬 Conversation",
        "🧠 Orchestration",
        "📊 Système",
        "🧭 Code Awareness",
        "💻 Workspace",
        "🧬 Évolution supervisée",
    ):
        assert section in result.response

    for obsolete_command in (
        "/fix",
        "/review",
        "/goal_status",
        "/projects",
        "/health",
        "/services",
    ):
        assert obsolete_command not in result.response


@pytest.mark.asyncio
async def test_planner_is_not_consulted_during_route_decision(monkeypatch):
    def forbidden_planner(*_args, **_kwargs):
        raise AssertionError("Planner must only be called by an executing pipeline")

    monkeypatch.setattr(
        "goal.planning.planner.AutonomousPlanner.create_plan",
        forbidden_planner,
    )

    decision, _ = await CoreOrchestrator().decide(
        "Analyse cette demande complexe"
    )

    assert decision.selected_route == "goal_engine"


@pytest.mark.asyncio
async def test_gateway_domain_request_reaches_the_resolver_not_the_llm(monkeypatch):
    """Non-regression : cf. les cas 'resolver' ajoutes au test parametrise
    ci-dessus. Verifie ici que le pipeline complet (`handle`) invoque bien
    le resolver et renvoie sa reponse, au lieu de tomber dans le chat LLM
    generique comme observe en production le 26/09/2026."""

    class ForbiddenAgentRouter:
        async def route(self, *_args, **_kwargs):
            raise AssertionError("Une demande de passerelle ne doit pas utiliser le LLM/agent router")

    class StubResolver:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def resolve(self, request):
            self.calls.append(request.text)
            from modules.capabilities.models import CapabilityDecision, CapabilityResult

            return CapabilityResult(
                status="action_required",
                response="Je peux me connecter a GitHub pour ca.",
                decision=CapabilityDecision(
                    decision="propose_gateway_connection",
                    confidence=0.95,
                    reason="test",
                    capability_type="gateway",
                    gateway_connector_id="github",
                    domain="repos",
                ),
            )

    resolver = StubResolver()
    orchestrator = CoreOrchestrator(
        agent_router=ForbiddenAgentRouter(),
        capability_resolver=resolver,
    )

    result = await orchestrator.handle("Ouvre mon repo")

    assert result.decision.selected_route == "resolver"
    assert resolver.calls == ["Ouvre mon repo"]
    assert result.response == "Je peux me connecter a GitHub pour ca."


@pytest.mark.asyncio
async def test_orchestrator_routes_timer(monkeypatch):
    class ForbiddenAgentRouter:
        async def route(self, *_args, **_kwargs):
            raise AssertionError("Timer must not use the LLM/agent router")

    orchestrator = CoreOrchestrator(agent_router=ForbiddenAgentRouter())
    result = await orchestrator.handle("Quelle heure est-il ?")

    assert result.decision.selected_route == "timer_engine"
    assert result.executor == "timer_module"
    assert result.decision.requires_llm is False
    assert result.metadata["source"] == "timer_module"


@pytest.mark.asyncio
async def test_timer_does_not_require_llm():
    decision, _ = await CoreOrchestrator().decide("Quel jour sommes-nous ?")

    assert decision.selected_route == "timer_engine"
    assert decision.requires_timer is True
    assert decision.requires_llm is False


@pytest.mark.asyncio
async def test_orchestrator_routes_identity(monkeypatch):
    calls = []

    async def fake_identity(kind, question=None, *, use_llm=True):
        calls.append((kind, question, use_llm))
        return {
            "response": "Je suis Néron.",
            "agent": "identity_module",
            "source": "identity_module:test",
            "llm_used": False,
        }

    monkeypatch.setattr(
        "core.pipeline.orchestrator.build_identity_response_async",
        fake_identity,
    )

    result = await CoreOrchestrator().handle("Qui es-tu ?")

    assert result.decision.selected_route == "identity_provider"
    assert result.executor == "identity_module"
    assert calls == [("identity_short", "Qui es-tu ?", False)]
    assert result.metadata["identity_llm_used"] is False


@pytest.mark.asyncio
async def test_orchestrator_routes_status(monkeypatch):
    calls = []

    async def fake_status(kind, *, question=None, use_llm=True):
        calls.append((kind, question, use_llm))
        return {
            "response": "Je fonctionne normalement.",
            "agent": "status_module",
            "source": "status_module",
            "status_kind": kind,
            "status": {"global_status": "healthy"},
            "llm_used": False,
        }

    monkeypatch.setattr(
        "core.pipeline.orchestrator.build_status_response_async",
        fake_status,
    )

    # "Comment vas-tu ?" est une CIVILITE, repondue localement sans modele
    # de langage — elle ne doit plus atteindre le module d'etat. On teste ici
    # une vraie demande d'etat de sante.
    result = await CoreOrchestrator().handle("Quel est ton etat de sante ?")

    assert result.decision.selected_route == "status_provider"
    assert result.executor == "status_module"
    assert calls == [("status_query", "Quel est ton etat de sante ?", False)]
    assert result.metadata["status_llm_used"] is False


@pytest.mark.asyncio
async def test_orchestrator_routes_location_to_status():
    decision, _ = await CoreOrchestrator().decide("Où es-tu ?")

    assert decision.selected_route == "status_provider"
    assert decision.requires_llm is False


@pytest.mark.asyncio
async def test_orchestrator_routes_goal():
    decision, _ = await CoreOrchestrator().decide(
        "Créer un agent nommé phase4_agent"
    )

    assert decision.selected_route == "goal_engine"
    assert decision.requires_goal_pipeline is True
    assert decision.requires_agent_factory is False


@pytest.mark.asyncio
async def test_goal_pipeline_only_runs_for_explicit_core_decision():
    """Une commande /goal explicite atteint bien le moteur Goal.

    `goal_orchestrator_factory` est deprecie et IGNORE depuis la phase 3 :
    le Coeur ne porte plus de pipeline Goal en process, il passe par le
    moteur (qui appelle le service goal en HTTP). Le test injecte donc un
    faux moteur au lieu d'un faux pipeline.
    """

    class FakeGoalResult:
        response = "objectif termine"

        def to_orchestrator_metadata(self):
            return {"status": "plan_finished"}

    class FakeGoalEngine:
        def __init__(self) -> None:
            self.calls = []

        async def execute(self, request):
            self.calls.append((request.objective, request.source))
            return FakeGoalResult()

    engine = FakeGoalEngine()
    orchestrator = CoreOrchestrator(goal_engine_instance=engine)

    result = await orchestrator.handle(
        "/goal cree un agent meteo",
        source_channel="telegram",
    )

    assert result.decision.selected_route == "goal_engine"
    assert engine.calls == [("cree un agent meteo", "telegram")]
    assert result.response == "objectif termine"
