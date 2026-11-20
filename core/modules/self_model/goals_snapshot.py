"""Objectifs, tâches et services enregistrés, vus par le Self Model.

Goal, ses tâches et son moteur relèvent du Manager de chantier : le Core
ne lit plus leur état en process (séparation Core/Goal, 58ab382). La
version de septembre importait goal.* et core.goal_engine directement, ce
qui ne fonctionne pas si Goal tourne sur une autre machine.
"""

from __future__ import annotations

from typing import Any


def _safe_registered_services() -> dict[str, Any]:
    try:
        from core.infrastructure.registry import service_registry

        services = service_registry.list_services()
        return {
            "count": len(services),
            "services": services,
            "source": "service_registry",
        }
    except Exception as exc:
        return {"count": 0, "services": [], "source": "service_registry", "error": str(exc)}


_MANAGER_OWNED = {"status": "external", "managed_by": "manager_de_chantier"}


def _safe_goal_engine() -> dict[str, Any]:
    return dict(_MANAGER_OWNED)


def _safe_goal_runtime() -> dict[str, Any]:
    return {
        "active_goal": None,
        "runtime_status": None,
        **_MANAGER_OWNED,
    }


def _safe_task_state() -> dict[str, Any]:
    return {"summary": None, **_MANAGER_OWNED}
