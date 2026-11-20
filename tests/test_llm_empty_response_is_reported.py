"""Core ne doit jamais rendre une reponse vide sans dire pourquoi.

Cas reel mesure le 03/09/2026 : le service LLM repond 200 avec
`result: ""` parce que Ollama a mis plus de 300 s (ReadTimeout apres
retries). La cause part alors dans `warning`, pas dans une erreur HTTP :
ni `raise_for_status` ni `provider_response.error` ne se declenchent.

Core renvoyait donc `{"response": "", "error": null}` apres 265 s d'attente.
L'appelant ne pouvait pas distinguer une panne d'une reponse legitimement
vide — c'est le defaut que ce test verrouille.
"""

from __future__ import annotations

import pytest

from core.pipeline.orchestrator import CoreOrchestrator
from core.providers.models import ProviderInfo, ProviderResponse


class _EmptyAnswerProvider:
    """Provider qui repond « avec succes » mais sans texte, comme en panne."""

    name = "llm"
    type = "llm"
    status = "healthy"
    capabilities = ["generate"]

    def __init__(self, warning: str | None) -> None:
        self._warning = warning

    async def health(self):
        return ProviderResponse(
            provider=self.name, action="health", status="healthy", result={}
        )

    async def execute(self, request):
        return ProviderResponse(
            provider=self.name,
            action=request.action,
            status="healthy",          # le service s'est declare sain
            result={"result": "", "model_used": "", "warning": self._warning},
            error=None,                # et n'a signale aucune erreur
        )


class _Registry:
    def __init__(self, provider) -> None:
        self._provider = provider

    def by_type(self, _type):
        return [ProviderInfo(name=self._provider.name, type="llm", status="healthy")]

    def get(self, _name):
        return self._provider


@pytest.mark.parametrize(
    "warning",
    ["ReadTimeout('')", None],
    ids=["avec_cause", "sans_cause"],
)
async def test_empty_llm_answer_is_never_returned_silently(monkeypatch, warning):
    monkeypatch.setattr(
        "core.pipeline.orchestrator.provider_registry",
        _Registry(_EmptyAnswerProvider(warning)),
    )
    orchestrator = CoreOrchestrator()

    text, executor, metadata = await orchestrator._execute_llm_provider(
        "Explique-moi ce qu est un noyau.",
        decision=None,
    )

    assert text.strip(), "Core ne doit pas renvoyer une chaine vide a l appelant"
    assert metadata.get("error"), "la cause doit etre remontee, pas avalee"
    assert executor == "llm"

    if warning:
        assert warning in metadata["error"]
