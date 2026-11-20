"""Le Coeur doit prononcer la reponse redigee par la memoire.

Le service memory repond a POST /memory/remember par {"memory": {...}}.
Le Coeur lit la reponse naturelle dans result["metadata"]["natural_response"].
Sans retrait de l'enveloppe par le provider, "metadata" n'est jamais a la
racine et Neron repond toujours "C'est memorise : <texte brut>" (17f8f54).
"""

from __future__ import annotations

import httpx
import pytest

from core.providers.memory.oblivia import ObliviaProvider
from core.providers.models import ProviderRequest

_NATURAL = "C'est corrige : Troyes est retire de ton historique de residence."


def _memory_service(request: httpx.Request) -> httpx.Response:
    # Forme exacte de neronMemory/app.py : return {"memory": ...}
    return httpx.Response(
        200,
        json={
            "memory": {
                "id": "m1",
                "content": "Je n'ai jamais habite a Troyes.",
                "metadata": {"natural_response": _NATURAL},
            }
        },
    )


@pytest.fixture
def mocked_memory_http(monkeypatch):
    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(_memory_service)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("core.providers.memory.oblivia.httpx.AsyncClient", client)


async def test_remember_envelope_is_removed(mocked_memory_http):
    response = await ObliviaProvider().execute(
        ProviderRequest(
            action="remember",
            payload={"content": "Je n'ai jamais habite a Troyes."},
        )
    )

    assert response.error is None
    assert response.result["metadata"]["natural_response"] == _NATURAL


@pytest.mark.parametrize(
    "payload",
    [{"results": []}, {"memory": {}, "extra": 1}, [1, 2]],
)
def test_other_payloads_are_left_untouched(payload):
    assert ObliviaProvider._deballer(payload) == payload
