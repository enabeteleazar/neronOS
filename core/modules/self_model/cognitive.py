"""Cognitive state and architecture snapshot for the Self Model."""

from __future__ import annotations

from typing import Any


def _architecture_snapshot() -> dict[str, Any]:
    return {
        "name": "NéronOS distributed kernel",
        "kernel": "core",
        "decision": "orchestrator",
        "goal_execution": "goal_engine",
        "capabilities": "provider_registry",
        "agents": "a2a_client",
        "agent_presence_execution": "provider_agent_planned",
        "memory": "memory_provider",
        "service_discovery": "service_registry",
        "self_awareness": "self_model",
        "principles": [
            "Core minimal",
            "Providers pour les capacités",
            "A2A pour les agents",
            "Goal Engine pour les objectifs",
            "Service Registry pour la topologie runtime",
            "Goal Engine développe les agents et leurs modules",
            "Provider Agent gérera la présence et l'exécution des agents",
            "Providers exposent uniquement des capacités stables",
        ],
        "separation": {
            "providers": {
                "kind": "provider",
                "role": "Exposer une capacité stable via Provider Registry",
                "managed_by": "provider_registry",
            },
            "agents": {
                "kind": "agent",
                "role": "Exécuter une capacité spécialisée via A2A",
                "developed_by": "goal_engine",
                "future_manager": "provider_agent",
            },
        },
    }


def _cognitive_state_from_status(
    status: dict[str, Any],
    diagnostics: list[str],
) -> dict[str, Any]:
    operationally_healthy = status.get("global_status") == "healthy"
    consolidated_healthy = operationally_healthy and not diagnostics
    state = "stable" if consolidated_healthy else "warning"
    runtime_mode = "normal" if consolidated_healthy else "prudent"
    severity_score = 0 if consolidated_healthy else 45
    return {
        "state": state,
        "severity_score": severity_score,
        "primary_issue": None if consolidated_healthy else "consolidated_state_warning",
        "runtime_pressure": "normal" if consolidated_healthy else "moderate",
        "autonomy_available": consolidated_healthy,
        "degraded_mode": not consolidated_healthy,
        "critical_services_ok": operationally_healthy,
        "runtime_mode": runtime_mode,
        "planner_enabled": True,
        "heavy_reasoning_allowed": consolidated_healthy,
        "autonomous_actions_allowed": True,
        "max_parallel_agents": 3 if consolidated_healthy else 1,
        "source": "self_model_consolidation",
    }
