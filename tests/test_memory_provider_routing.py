from __future__ import annotations

import pytest

from core.pipeline.intent.intent_router import Intent, IntentRouter
from core.pipeline.orchestrator import CoreOrchestrator
from core.providers.models import ProviderInfo, ProviderResponse


class ForbiddenAgentRouter:
    async def route(self, *_args, **_kwargs):
        raise AssertionError("memory_search must not reach the LLM")


class FakeMemoryProvider:
    name = "oblivia"
    type = "memory"
    status = "healthy"
    capabilities = ["remember", "recall", "search", "status"]

    def __init__(self, results: list[dict] | None = None) -> None:
        self.calls: list[object] = []
        self.results = results or []
        self.memory: list[str] = []

    async def health(self):
        return ProviderResponse(
            provider=self.name,
            action="health",
            status="healthy",
            result={"ok": True},
        )

    async def execute(self, request):
        self.calls.append(request)
        if request.action == "remember":
            content = str(request.payload.get("content") or "")
            self.memory.append(content)
            return ProviderResponse(
                provider=self.name,
                action=request.action,
                status="healthy",
                result={"content": content},
            )
        if request.action in {"recall", "search"} and self.memory:
            query = str(request.payload.get("query") or "").lower()
            matches = [
                content
                for content in self.memory
                if not query or query in content.lower()
            ]
            return ProviderResponse(
                provider=self.name,
                action=request.action,
                status="healthy",
                result=[
                    {
                        "record": {"content": content},
                        "backend": "fake",
                        "score": 1.0,
                    }
                    for content in matches
                ],
            )
        return ProviderResponse(
            provider=self.name,
            action=request.action,
            status="healthy",
            result=self.results,
        )


class FakeProviderRegistry:
    def __init__(self, provider: FakeMemoryProvider) -> None:
        self.provider = provider
        self.a2a_calls: list[tuple[str, object]] = []

    def by_type(self, provider_type):
        if provider_type != "memory":
            return []
        return [
            ProviderInfo(
                name=self.provider.name,
                type="memory",
                status="healthy",
                capabilities=["remember", "recall", "search", "status"],
            )
        ]

    def get(self, name):
        if name == self.provider.name:
            return self.provider
        return None

    async def execute_via_a2a(self, name, request):
        self.a2a_calls.append((name, request))
        return await self.provider.execute(request)


MEMORY_SEARCH_QUERIES = [
    ("Recherche Phase 2", "phase 2"),
    ("Cherche Phase 2", "phase 2"),
    ("Retrouve Phase 2", "phase 2"),
    ("Recherche dans ta mémoire Phase 2", "phase 2"),
    ("Qu'as-tu mémorisé sur Oblivia ?", "oblivia"),
    ("Que sais-tu sur SQLite ?", "sqlite"),
    ("Retrouve mes notes sur Goal Engine", "goal engine"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("query", "memory_query"), MEMORY_SEARCH_QUERIES)
async def test_intent_detects_memory_search(query: str, memory_query: str):
    result = await IntentRouter().route(query)

    assert result.intent == Intent.MEMORY_SEARCH
    assert result.confidence_score >= 0.85


@pytest.mark.asyncio
async def test_memory_search_routes_to_provider_registry(monkeypatch):
    provider = FakeMemoryProvider(
        results=[
            {
                "record": {
                    "content": "Le test de la Phase 2 a été validé le 29 juin 2026."
                },
                "backend": "sqlite",
                "score": 1.0,
            }
        ]
    )
    monkeypatch.setattr(
        "core.pipeline.orchestrator.provider_registry",
        FakeProviderRegistry(provider),
    )

    result = await CoreOrchestrator(agent_router=ForbiddenAgentRouter()).handle(
        "Recherche Phase 2"
    )

    assert result.intent == "memory_search"
    assert result.decision.selected_route == "memory_provider"
    assert result.decision.requires_memory is True
    assert result.decision.requires_llm is False
    assert result.executor == "oblivia"
    assert result.model is None
    assert "J’ai trouvé 1 résultat en mémoire" in result.response
    assert "- Le test de la Phase 2 a été validé le 29 juin 2026." in result.response
    assert provider.calls
    assert provider.calls[0].action == "search"
    assert provider.calls[0].payload["query"] == "phase 2"
    assert result.metadata["memory_action"] == "search"
    assert result.metadata["memory_query"] == "phase 2"
    assert result.metadata["memory_results_count"] == 1
    assert result.metadata["llm_used"] is False


@pytest.mark.asyncio
async def test_memory_search_returns_clear_message_without_results(monkeypatch):
    provider = FakeMemoryProvider(results=[])
    monkeypatch.setattr(
        "core.pipeline.orchestrator.provider_registry",
        FakeProviderRegistry(provider),
    )

    result = await CoreOrchestrator(agent_router=ForbiddenAgentRouter()).handle(
        "Qu'as-tu mémorisé sur Oblivia ?"
    )

    assert result.intent == "memory_search"
    assert result.executor == "oblivia"
    assert result.response == "Je n’ai trouvé aucun souvenir correspondant à « oblivia »."
    assert result.metadata["memory_query"] == "oblivia"
    assert result.metadata["memory_results_count"] == 0
    assert result.metadata["llm_used"] is False


@pytest.mark.asyncio
async def test_memory_remember_routes_to_provider(monkeypatch):
    provider = FakeMemoryProvider()
    monkeypatch.setattr(
        "core.pipeline.orchestrator.provider_registry",
        FakeProviderRegistry(provider),
    )

    result = await CoreOrchestrator(agent_router=ForbiddenAgentRouter()).handle(
        "Mémorise que la Phase 2 Architecture Providers + A2A est validée."
    )

    assert result.intent == "memory_remember"
    assert result.decision.selected_route == "memory_provider"
    assert result.decision.requires_llm is False
    assert result.executor == "oblivia"
    assert result.model is None
    assert provider.calls[0].action == "remember"
    assert provider.calls[0].payload["content"] == (
        "la Phase 2 Architecture Providers + A2A est validée"
    )
    assert result.metadata["memory_action"] == "remember"
    assert result.metadata["llm_used"] is False


@pytest.mark.asyncio
async def test_memory_recall_routes_to_provider(monkeypatch):
    provider = FakeMemoryProvider()
    provider.memory.append("la Phase 2 est validée avec Oblivia")
    monkeypatch.setattr(
        "core.pipeline.orchestrator.provider_registry",
        FakeProviderRegistry(provider),
    )

    result = await CoreOrchestrator(agent_router=ForbiddenAgentRouter()).handle(
        "Que viens-tu de mémoriser ?"
    )

    assert result.intent == "memory_recall"
    assert result.decision.selected_route == "memory_provider"
    assert result.executor == "oblivia"
    assert provider.calls[0].action == "recall"
    assert result.metadata["memory_action"] == "recall"
    assert result.metadata["memory_results_count"] == 1
    assert result.metadata["llm_used"] is False


@pytest.mark.asyncio
async def test_memory_remember_then_search_finds_content(monkeypatch):
    provider = FakeMemoryProvider()
    monkeypatch.setattr(
        "core.pipeline.orchestrator.provider_registry",
        FakeProviderRegistry(provider),
    )
    orchestrator = CoreOrchestrator(agent_router=ForbiddenAgentRouter())

    remembered = await orchestrator.handle(
        "Mémorise que la Phase 2 Architecture Providers + A2A est validée avec Oblivia comme Memory Provider."
    )
    searched = await orchestrator.handle("Recherche Phase 2")

    assert remembered.executor == "oblivia"
    assert remembered.metadata["memory_action"] == "remember"
    assert searched.executor == "oblivia"
    assert searched.metadata["memory_action"] == "search"
    assert searched.metadata["memory_results_count"] >= 1
    assert "Phase 2 Architecture Providers + A2A" in searched.response
    assert searched.metadata["llm_used"] is False
