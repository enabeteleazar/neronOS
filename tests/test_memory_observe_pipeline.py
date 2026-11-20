"""Mémorisation à l'entrée du pipeline (cde7ea0 + correction du 08/09/2026).

Perdue lors de la réintégration du Core (58ab382). Contrat HTTP :
POST /memory/observe {"text", "source"} sur le service memory, éventuellement
sur un autre serveur. Règles verrouillées ici :

- tout message est observé, sauf ceux de la route mémoire (doublons de faits,
  question stockée dans sa propre réponse) et les civilités / l'aide ;
- l'observation ne retarde jamais la réponse ;
- le contexte mémoire est injecté dans le prompt de conversation générale.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from core.pipeline import orchestrator as orch
from core.pipeline.orchestrator import CoreOrchestrator
from core.providers.models import ProviderInfo, ProviderResponse


class _Memory:
    name = "oblivia-memory"

    def __init__(self, observe_delay: float = 0.0, answer: str | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.observe_delay = observe_delay
        self.answer = answer

    async def execute(self, request):
        self.calls.append((request.action, dict(request.payload)))
        if request.action == "observe":
            await asyncio.sleep(self.observe_delay)
        result = {"answer": self.answer} if request.action == "recall" else {}
        return ProviderResponse(
            provider=self.name, action=request.action, status="healthy", result=result
        )

    def observed(self) -> list[str]:
        return [p["text"] for a, p in self.calls if a == "observe"]


class _LLM:
    name = "llm"

    def __init__(self):
        self.prompts: list[str] = []

    async def execute(self, request):
        self.prompts.append(request.payload["prompt"])
        return ProviderResponse(
            provider=self.name,
            action=request.action,
            status="healthy",
            result={"result": "Réponse.", "model_used": "fake"},
        )


class _Registry:
    def __init__(self, memory, llm):
        self._by_type = {"memory": memory, "llm": llm}

    def by_type(self, kind):
        provider = self._by_type.get(kind)
        return [ProviderInfo(name=provider.name, type=kind, status="healthy")] if provider else []

    def get(self, name):
        return next((p for p in self._by_type.values() if p.name == name), None)


@pytest.fixture
def stack(monkeypatch):
    def install(**memory_kwargs):
        memory, llm = _Memory(**memory_kwargs), _LLM()
        monkeypatch.setattr(orch, "provider_registry", _Registry(memory, llm))
        return memory, llm

    return install


async def _drain():
    if orch._OBSERVE_TASKS:
        await asyncio.gather(*list(orch._OBSERVE_TASKS))


async def test_ordinary_message_is_observed(stack):
    memory, _ = stack()
    await CoreOrchestrator().handle("Explique-moi Kubernetes")
    await _drain()
    assert memory.observed() == ["Explique-moi Kubernetes"]
    assert ("observe", {"text": "Explique-moi Kubernetes", "source": "utilisateur"}) in memory.calls


@pytest.mark.parametrize(
    "query",
    ["Bonjour", "/help", "Souviens-toi que mon vélo est un Decathlon Riverside"],
)
async def test_memory_route_and_civilities_are_not_observed(stack, query):
    memory, _ = stack()
    result = await CoreOrchestrator().handle(query)
    await _drain()
    assert result.decision.selected_route in {"smalltalk", "help_provider", "memory_provider"}
    assert memory.observed() == []


async def test_observation_never_delays_the_answer(stack):
    stack(observe_delay=2.0)
    started = time.monotonic()
    await CoreOrchestrator().handle("Explique-moi Kubernetes")
    assert time.monotonic() - started < 1.5
    await _drain()


async def test_memory_context_reaches_the_llm_prompt(stack):
    _, llm = stack(answer="Tu habites à Nantes.")
    result = await CoreOrchestrator().handle("Explique-moi Kubernetes")
    await _drain()
    assert llm.prompts == [
        "Contexte connu sur l'utilisateur : Tu habites à Nantes.\n\nExplique-moi Kubernetes"
    ]
    assert result.metadata["memory_context_used"] is True
