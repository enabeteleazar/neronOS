"""Le Coeur ne doit declencher qu'UNE chaine de memorisation par message.

Mesure le 08/09/2026 en production. `handle()` envoyait chaque message a
/memory/observe AVANT de router, puis la route memory_provider appelait
/memory/remember. Un « Retiens que mon velo est un Decathlon Riverside. »
partait donc dans les deux chaines d'extraction a la fois et produisait
deux enregistrements bruts et trois faits, dont `habite_a = Riverside`.

Le correctif : observer apres la decision, et pas du tout lorsque la route
va deja ecrire elle-meme.
"""

from __future__ import annotations

import pytest

from core.pipeline.orchestrator import CoreOrchestrator

from tests._memory_stack import memory_stack


class RefuseLeLLM:
    async def route(self, *_args, **_kwargs):
        raise AssertionError("ce chemin ne doit pas passer par le LLM")


@pytest.fixture
def orchestrateur(tmp_path, monkeypatch):
    """Orchestrateur relie a un service memoire isole, observe espionne."""
    registry, provider = memory_stack(tmp_path)
    monkeypatch.setattr(
        "core.pipeline.orchestrator.provider_registry", registry
    )

    observations: list[str] = []

    async def _espion(self, query: str) -> None:
        observations.append(query)

    monkeypatch.setattr(
        CoreOrchestrator, "_send_to_oblivia_observe", _espion
    )
    return CoreOrchestrator(agent_router=RefuseLeLLM()), provider, observations


@pytest.mark.asyncio
async def test_an_explicit_memorisation_is_not_observed_as_well(orchestrateur):
    """Le cas exact du 08/09 : une seule chaine doit partir."""
    core, _provider, observations = orchestrateur

    resultat = await core.handle("Retiens que mon velo est un Decathlon Riverside.")

    assert resultat.decision.selected_route == "memory_provider"
    assert resultat.metadata["memory_action"] == "remember"
    assert observations == [], (
        "le message part deja en memorisation explicite : l'observer en plus "
        f"declenche la seconde chaine d'extraction ({observations})"
    )


@pytest.mark.asyncio
async def test_that_single_chain_still_writes_the_fact(orchestrateur):
    """Ne plus observer ne doit pas faire perdre l'information."""
    core, provider, _ = orchestrateur

    await core.handle("Retiens que mon velo est un Decathlon Riverside.")

    faits = [f for f in provider._manager.sqlite.list_facts() if not f.retracted]
    assert len(faits) == 1
    assert "Riverside" in faits[0].object


@pytest.mark.asyncio
async def test_an_ordinary_message_is_still_observed(orchestrateur):
    """L'observation passive reste la voie normale de tout le reste."""
    core, _provider, observations = orchestrateur

    await core.handle("Quelle heure est-il ?")

    assert observations == ["Quelle heure est-il ?"]


@pytest.mark.asyncio
async def test_a_question_never_writes_a_fact_or_a_draft(orchestrateur):
    """Une question interroge la memoire, elle ne la nourrit pas.

    On ne verifie pas la route empruntee : « Quel velo est-ce que je
    possede ? » part aujourd'hui vers llm_provider parce que le mappage
    ("memory", ...) -> CONVERSATION de intent_router.py classe les questions
    memoire en conversation. C'est un defaut connu, distinct de celui-ci et
    hors du perimetre de cette mission. Ce qui doit etre vrai quelle que
    soit la route, c'est qu'aucune ecriture ne s'ensuit.
    """
    core, provider, _ = orchestrateur

    await core.handle("Retiens que mon velo est un Decathlon Riverside.")
    faits_avant = len(provider._manager.sqlite.list_facts())
    brouillons_avant = len(provider._manager.sqlite.list_candidates())

    await core.handle("Quel velo est-ce que je possede ?")

    assert len(provider._manager.sqlite.list_facts()) == faits_avant
    assert len(provider._manager.sqlite.list_candidates()) == brouillons_avant


@pytest.mark.asyncio
async def test_repeating_the_same_order_does_not_duplicate(orchestrateur):
    """Idempotence de bout en bout, vue du Coeur."""
    core, provider, _ = orchestrateur

    for _ in range(3):
        await core.handle("Retiens que mon velo est un Decathlon Riverside.")

    faits = [f for f in provider._manager.sqlite.list_facts() if not f.retracted]
    assert len(faits) == 1
