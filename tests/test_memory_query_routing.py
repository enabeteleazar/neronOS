"""Une question sur soi doit interroger la memoire, pas le LLM.

Mesure le 07/09/2026. « Quel velo est-ce que je possede ? » restait sans
reponse pendant 60 s : la question partait dans le LLM conversationnel
alors que l'information etait en memoire, a portee de requete.

La cause n'etait pas le mappage target/operation du classifieur ML — il
n'est meme pas atteint ici. `detect_memory_intent` reconnaissait des
FORMULATIONS precises (« quel est mon metier ? ») et laissait passer les
autres tournures de la meme question. Le discriminant retenu n'est plus la
formulation mais la personne : une question a la premiere personne
interroge la memoire, une question generale n'a aucun marqueur personnel.
"""

from __future__ import annotations

import pytest

from core.modules.memory import detect_memory_intent
from core.pipeline.orchestrator import CoreOrchestrator
from memory.oblivia.schemas import MemoryRecord

from tests._memory_stack import memory_stack


class RefuseLeLLM:
    """Le chemin de lecture memoire ne doit solliciter aucun modele."""

    async def route(self, *_args, **_kwargs):
        raise AssertionError(
            "une question memoire ne doit pas passer par le LLM conversationnel"
        )


@pytest.fixture
def orchestrateur(tmp_path, monkeypatch):
    registry, provider = memory_stack(tmp_path)
    monkeypatch.setattr(
        "core.pipeline.orchestrator.provider_registry", registry
    )
    return CoreOrchestrator(agent_router=RefuseLeLLM()), provider


def _memoriser(provider, phrase: str) -> None:
    provider._manager.remember(MemoryRecord(content=phrase, source="utilisateur"))


# ── Routage ────────────────────────────────────────────────────────────

QUESTIONS_MEMOIRE = [
    "Comment s'appelle mon collegue ?",
    "Quel velo est-ce que je possede ?",
    "Quel est mon metier ?",
    "Ou est-ce que j'habite ?",
    "Qu'est-ce que tu sais sur mon velo ?",
    "Quelle est ma couleur preferee ?",
]

QUESTIONS_GENERALES = [
    "Quelle est la capitale de la France ?",
    "Explique-moi Docker.",
    "Qui etait Napoleon ?",
    "Comment fonctionne Linux ?",
    "Combien font 2 + 2 ?",
]


@pytest.mark.parametrize("question", QUESTIONS_MEMOIRE)
def test_a_personal_question_is_detected_as_a_recall(question):
    detecte = detect_memory_intent(question)

    assert detecte["matched"] is True
    assert detecte["kind"] == "recall"


@pytest.mark.parametrize("question", QUESTIONS_GENERALES)
def test_a_general_question_is_not_a_memory_query(question):
    assert detect_memory_intent(question)["matched"] is False


@pytest.mark.parametrize(
    "question",
    [
        # Premiere personne, mais demande d'action : pas un souvenir.
        "Est-ce que je peux redemarrer le service ?",
        # « moi » n'est pas un marqueur de question personnelle.
        "Explique-moi Docker.",
    ],
)
def test_first_person_alone_is_not_enough(question):
    assert detect_memory_intent(question)["matched"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("question", QUESTIONS_MEMOIRE)
async def test_a_personal_question_routes_to_memory(orchestrateur, question):
    core, _provider = orchestrateur

    decision, _ = await core.decide(question)

    assert decision.selected_route == "memory_provider"
    assert decision.intent == "memory_recall"
    assert decision.requires_llm is False


@pytest.mark.asyncio
@pytest.mark.parametrize("question", QUESTIONS_GENERALES)
async def test_a_general_question_still_goes_to_the_llm(orchestrateur, question):
    core, _provider = orchestrateur

    decision, _ = await core.decide(question)

    assert decision.selected_route != "memory_provider"


# ── Lecture ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_colleague_question_answers_from_memory(orchestrateur):
    core, provider = orchestrateur
    _memoriser(provider, "Mon collegue s'appelle Killian.")

    resultat = await core.handle("Comment s'appelle mon collegue ?")

    assert "Killian" in resultat.response
    assert resultat.metadata["memory_action"] == "recall"


@pytest.mark.asyncio
async def test_the_bike_question_answers_from_memory(orchestrateur):
    """Le cas qui restait 60 s sans reponse."""
    core, provider = orchestrateur
    _memoriser(provider, "mon velo est un Decathlon Riverside")

    resultat = await core.handle("Quel velo est-ce que je possede ?")

    assert "Riverside" in resultat.response


@pytest.mark.asyncio
async def test_reading_writes_nothing(orchestrateur):
    """Une lecture ne cree ni fait, ni brouillon."""
    core, provider = orchestrateur
    _memoriser(provider, "mon velo est un Decathlon Riverside")
    faits = len(provider._manager.sqlite.list_facts())
    brouillons = len(provider._manager.sqlite.list_candidates())

    await core.handle("Quel velo est-ce que je possede ?")

    assert len(provider._manager.sqlite.list_facts()) == faits
    assert len(provider._manager.sqlite.list_candidates()) == brouillons


# ── Ce que la memoire ignore ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_unknown_question_admits_it_knows_nothing(orchestrateur):
    core, _provider = orchestrateur

    resultat = await core.handle("Quel est le nom de mon ancien collegue ?")

    assert "aucun souvenir" in resultat.response.lower()


@pytest.mark.asyncio
async def test_an_unknown_question_invents_nothing(orchestrateur):
    """Ne rien savoir ne doit jamais devenir un fait."""
    core, provider = orchestrateur

    await core.handle("Quel est le nom de mon ancien collegue ?")

    assert provider._manager.sqlite.list_facts() == []
    assert provider._manager.sqlite.list_candidates() == []


@pytest.mark.asyncio
async def test_the_answer_never_comes_from_a_model(orchestrateur):
    """RefuseLeLLM leve si le LLM est sollicite : ce test le prouve."""
    core, provider = orchestrateur
    _memoriser(provider, "Mon collegue s'appelle Killian.")

    resultat = await core.handle("Comment s'appelle mon collegue ?")

    assert resultat.metadata.get("llm_used") is False


# ── L'ecriture reste inchangee ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_explicit_memorisation_still_writes(orchestrateur):
    """La correction du routage ne touche pas au chemin d'ecriture."""
    core, provider = orchestrateur

    resultat = await core.handle(
        "Retiens que mon velo est un Decathlon Riverside."
    )

    assert resultat.metadata["memory_action"] == "remember"
    faits = [f for f in provider._manager.sqlite.list_facts() if not f.retracted]
    assert len(faits) == 1
    assert faits[0].provenance == "explicit_user"
