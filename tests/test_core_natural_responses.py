from __future__ import annotations

import pytest

from core.modules.goal_status_response import build_goal_status_response_async
from core.modules.memory import service as memory_service
from core.modules.memory.service import build_memory_response_async
from core.modules.natural_response import _validate_response
from core.modules.runtime_response import build_runtime_response_async
from core.modules.status.detector import detect_status_intent
from core.modules.status.service import build_status_response
from core.pipeline.orchestrator import CoreOrchestrator
from core.providers.models import ProviderInfo, ProviderResponse

def test_natural_response_rejects_system_paths():
    assert (
        _validate_response(
            "Je conserve ces informations dans /etc/neron/server/memory.",
            max_chars=300,
            max_sentences=2,
            require_first_person=True,
        )
        is None
    )


@pytest.mark.asyncio
async def test_memory_recall_fallback_is_natural(monkeypatch):
    class Registry:
        def by_type(self, provider_type):
            return [ProviderInfo(
                name="oblivia",
                type=provider_type,
                status="healthy",
                capabilities=["recall"],
            )]

        async def execute_via_a2a(self, _name, request):
            return ProviderResponse(
                provider="oblivia",
                action=request.action,
                status="healthy",
                result={
                    "answer": "Je me souviens que ma mémoire repose sur SQLite et Obsidian.",
                    "facts": [],
                    "results": [],
                },
            )

    monkeypatch.setattr(memory_service, "provider_registry", Registry())

    result = await build_memory_response_async(
        "recall",
        "Que sais-tu de ta mémoire ?",
        use_llm=False,
    )

    assert result["memory_response_mode"] == "provider"
    assert result["memory_llm_used"] is False
    assert result["response"].startswith("Je me souviens")
    assert "SQLite" in result["response"]
    assert "Obsidian" in result["response"]
    assert "- [" not in result["response"]


@pytest.mark.asyncio
async def test_memory_recall_uses_provider_answer_without_llm(monkeypatch):
    class Registry:
        def by_type(self, provider_type):
            return [ProviderInfo(
                name="oblivia",
                type=provider_type,
                status="healthy",
                capabilities=["recall"],
            )]

        async def execute_via_a2a(self, _name, request):
            return ProviderResponse(
                provider="oblivia",
                action=request.action,
                status="healthy",
                result={
                    "answer": "Je me souviens qu'Oblivia porte la mémoire centrale de Néron.",
                    "facts": [],
                    "results": [],
                },
            )

    monkeypatch.setattr(memory_service, "provider_registry", Registry())

    result = await build_memory_response_async(
        "recall",
        "Que sais-tu de ta mémoire ?",
    )

    assert result["memory_llm_used"] is False
    assert result["a2a_used"] is True
    assert result["response"].startswith("Je me souviens")


def test_status_response_keeps_raw_payload_but_returns_natural_text():
    result = build_status_response("core_status")

    assert result["status"]
    assert result["raw_response"].startswith("État de Néron")
    assert result["response"].startswith("Mon système")
    assert "Timestamp" not in result["response"]


@pytest.mark.asyncio
async def test_runtime_response_fallback_is_natural():
    result = await build_runtime_response_async(
        {"runtime_mode": "normal"},
        {"exists": True},
        use_llm=False,
    )

    assert result["llm_used"] is False
    assert result["response"] == "Tous mes services principaux sont actuellement opérationnels."


@pytest.mark.asyncio
async def test_goal_status_response_is_not_json():
    result = await build_goal_status_response_async(
        {
            "goal_id": "goal-1",
            "status": "tasks_completed",
            "current_step": "validation",
            "progress": 0.8,
            "test_status": "completed",
            "registry_status": "not_registered",
        },
        question="Où en est mon objectif ?",
        use_llm=False,
    )

    assert result["llm_used"] is False
    assert result["response"].startswith("Ton objectif")
    assert "{" not in result["response"]
    assert "tests" in result["response"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_route"),
    [
        ("Que sais-tu de ta mémoire ?", "memory_provider"),
        ("Comment est organisée ta mémoire ?", "memory_provider"),
        ("Quel est ton état actuel ?", "status_provider"),
        ("Comment va ton système ?", "status_provider"),
        ("Quels services sont actifs ?", "status_provider"),
        ("Quels modules sont chargés ?", "status_provider"),
        ("Quels modules sont disponibles ?", "status_provider"),
        ("Ton système fonctionne-t-il correctement ?", "status_provider"),
        # Civilite, pas demande d'etat : reponse locale « Tout va bien, merci »
        # plutot qu'un rapport technique (decision du 03/09/2026, 80d6794).
        # Une demande d'etat explicite (« Comment va ton systeme ? ») reste
        # sur status_provider. Voir tests/test_smalltalk_stays_local.py.
        ("Comment vas-tu ?", "smalltalk"),
        ("As-tu détecté des problèmes ?", "status_provider"),
        ("Le Core fonctionne-t-il ?", "status_provider"),
        ("Où en est mon objectif ?", "tool_router"),
    ],
)
async def test_natural_core_questions_route_to_core_modules(query, expected_route):
    decision, _ = await CoreOrchestrator().decide(query)

    assert decision.selected_route == expected_route


@pytest.mark.parametrize(
    ("query", "expected_kind"),
    [
        ("Quels modules sont chargés ?", "modules_query"),
        ("Quels modules sont disponibles ?", "modules_query"),
        ("Quels services sont actifs ?", "services_query"),
        ("Quel est ton état actuel ?", "status_query"),
        ("Ton système fonctionne-t-il correctement ?", "health_query"),
        ("Comment vas-tu ?", "health_query"),
        ("As-tu détecté des problèmes ?", "health_query"),
        ("Le Core fonctionne-t-il ?", "health_query"),
    ],
)
def test_status_detector_classifies_system_state_questions(query, expected_kind):
    result = detect_status_intent(query)

    assert result["matched"] is True
    assert result["kind"] == expected_kind


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "Quels modules sont chargés ?",
        "Quels services sont actifs ?",
        "Ton système fonctionne-t-il correctement ?",
    ],
)
async def test_status_questions_never_route_to_llm_provider(query):
    decision, _ = await CoreOrchestrator().decide(query)

    assert decision.selected_route == "status_provider"
    assert decision.selected_route != "llm_provider"


@pytest.mark.asyncio
async def test_modules_query_uses_real_status_payload_without_invented_modules():
    result = await CoreOrchestrator().handle("Quels modules sont chargés ?")
    forbidden_terms = [
        "Superviseur de Raisonnement",
        "Cache de Contexte Dynamique",
        "Nucleus",
        "Chain-of-Thought",
    ]

    assert result.decision.selected_route == "status_provider"
    assert result.metadata["status_kind"] == "modules_query"
    assert result.metadata["status_llm_used"] is False
    assert "Identity" in result.response
    assert "Status" in result.response
    assert "Timer" in result.response
    for term in forbidden_terms:
        assert term not in result.response
