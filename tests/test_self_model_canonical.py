from __future__ import annotations

import pytest

import asyncio
import inspect
from pathlib import Path


def test_core_modules_self_model_is_importable_and_structured():
    from core.modules.self_model import build_self_model_snapshot, get_self_model_status

    snapshot = build_self_model_snapshot()

    assert set(snapshot) >= {"identity", "memory", "status", "goal", "generated_at"}
    assert isinstance(snapshot["identity"], dict)
    assert isinstance(snapshot["memory"], dict)
    assert isinstance(snapshot["status"], dict)
    assert isinstance(snapshot["goal"], dict)
    assert get_self_model_status()["status"]["core"] == "online"


def test_self_model_has_no_direct_operational_collectors():
    import core.modules.self_model.service as self_model_service

    source = inspect.getsource(self_model_service).lower()

    for forbidden in (
        "import psutil",
        "subprocess",
        "systemctl",
        "prometheus_client",
        "watchdog_agent",
        "doctor.",
        "modules.health",
    ):
        assert forbidden not in source


def test_legacy_self_model_imports_point_to_canonical_module():
    """Un seul modele de soi, et plus aucun chemin d'acces herite.

    Ce test verifiait que core.self_model et modules.self_model
    reexportaient l'implementation canonique. La consolidation est finie :
    ces deux passerelles ont ete supprimees. Le garde-fou devient donc leur
    ABSENCE — sans quoi une reimplementation parallele pourrait revenir
    sans qu'on le voie.
    """
    import importlib

    import core.modules.self_model.service as canonical

    assert canonical.SelfModel is not None
    assert canonical.build_self_model_snapshot is not None
    assert canonical.get_self_model is not None

    for herite in ("core.self_model.self_model", "modules.self_model.self_model"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(herite)


def test_status_keeps_operational_payload_responsibility():
    from core.modules.status.service import build_status_payload

    payload = build_status_payload()

    assert payload["core"] == "online"
    assert "resources" in payload
    assert "services" in payload
    assert "sources" in payload
    assert payload["sources"]["services"]["status"] == "local_payload"


def test_self_model_routes_use_structured_snapshot():
    from core.api import self_model_routes as self_model_context_routes

    status = asyncio.run(self_model_context_routes.self_model_status())
    context = asyncio.run(self_model_context_routes.self_model_context())

    # /self-model/status expose l'etat de sante sous "health" ; la cle
    # "status" appartient a /self-model/context.
    assert "health" in status
    assert "runtime_mode" in status
    assert "identity" in context
    assert "memory" in context
    assert "status" in context
    assert "goal" in context


def test_self_status_question_routes_to_self_model_not_llm():
    from core.pipeline.orchestrator import CoreOrchestrator

    decision, _ = asyncio.run(
        CoreOrchestrator().decide("Que sais-tu de toi-même ?")
    )

    assert decision.intent == "self_status"
    assert decision.selected_route == "tool_router"


def test_internal_state_question_routes_to_self_model_not_status():
    from core.pipeline.orchestrator import CoreOrchestrator

    decision, _ = asyncio.run(
        CoreOrchestrator().decide("Quel est ton état interne ?")
    )

    assert decision.intent == "self_status"
    assert decision.selected_route == "tool_router"


def test_self_model_leaves_goals_and_tasks_to_the_manager():
    import core.modules.self_model.service as service

    snapshot = service.build_self_model_snapshot()

    for key in ("goal", "tasks", "goal_engine"):
        assert snapshot[key]["status"] == "external"
        assert snapshot[key]["managed_by"] == "manager_de_chantier"
    assert snapshot["active_goal"] is None
    assert not any("Goal" in item or "tâche" in item for item in snapshot["diagnostics"])


def test_self_model_source_does_not_reintroduce_old_direct_collectors():
    root = Path(__file__).parents[1] / "core" / "modules" / "self_model"
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))

    assert "psutil" not in text
    assert "systemctl" not in text
    assert "prometheus_client" not in text
