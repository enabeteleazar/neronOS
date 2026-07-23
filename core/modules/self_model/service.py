from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.modules.self_model.identity_snapshot import _safe_identity
from core.modules.self_model.state import (
    STATE_PATH,
    _now_iso,
    _read_state,
    _write_state,
)
from core.modules.self_model.providers_snapshot import (
    _agent_topology,
    _normalize_agent,
    _normalize_provider,
    _safe_a2a,
    _safe_agents,
    _safe_memory_status,
    _safe_providers,
)
from core.modules.self_model.goals_snapshot import (
    _safe_goal_engine,
    _safe_goal_runtime,
    _safe_registered_services,
    _safe_task_state,
)
from core.modules.self_model.runtime_snapshot import (
    _runtime_from_status,
    _services_from_status,
)
from core.modules.self_model.cognitive import (
    _architecture_snapshot,
    _cognitive_state_from_status,
)
from core.modules.status.service import build_status_payload


def _capability_snapshot(
    providers: dict[str, Any],
    a2a: dict[str, Any],
    agents: dict[str, Any],
) -> dict[str, Any]:
    provider_capabilities = set(providers.get("capabilities") or [])
    agent_capabilities = {
        capability
        for collection in (
            a2a.get("agents") or [],
            agents.get("agents") or [],
        )
        for source in collection
        if isinstance(source, dict)
        for capability in source.get("capabilities", [])
    }
    return {
        "available": sorted(provider_capabilities | agent_capabilities),
        "providers": sorted(provider_capabilities),
        "agents": sorted(agent_capabilities),
        "source": ["provider_registry", "a2a_client", "agent_registry"],
    }


def build_self_model_snapshot() -> dict[str, Any]:
    status = build_status_payload()
    memory = _safe_memory_status()
    goal = _safe_goal_runtime()
    tasks = _safe_task_state()
    identity = _safe_identity()
    providers = _safe_providers()
    a2a = _safe_a2a()
    agents = _safe_agents()
    agent_topology = _agent_topology(agents, a2a)
    registered_services = _safe_registered_services()
    goal_engine = _safe_goal_engine()
    capabilities = _capability_snapshot(providers, a2a, agents)
    architecture = _architecture_snapshot()
    runtime = _runtime_from_status(status)
    services = _services_from_status(status)
    diagnostics: list[str] = []
    recommendations: list[str] = []

    if status.get("global_status") != "healthy":
        diagnostics.append("Status opérationnel dégradé.")
        recommendations.append(
            "Consulter le module Status avant une action lourde."
        )

    goal_runtime = goal.get("runtime_status") or {}
    goal_runtime_status = str(goal_runtime.get("status") or "").lower()
    if goal_runtime_status in {"interrupted", "failed", "error"}:
        diagnostics.append(
            f"Goal Runtime en état {goal_runtime_status}."
        )
        recommendations.append(
            "Réconcilier ou relancer explicitement le goal interrompu."
        )

    task_summary = tasks.get("summary") or {}
    failed_tasks = int(task_summary.get("failed") or 0)
    if failed_tasks:
        diagnostics.append(f"{failed_tasks} tâche(s) en échec.")
        recommendations.append(
            "Examiner les tâches en échec avant de déclarer l’état stable."
        )

    status_sources = status.get("sources") or {}
    unavailable_sources = sorted(
        name
        for name in ("doctor", "watchdog", "prometheus")
        if (status_sources.get(name) or {}).get("status") != "integrated"
    )
    if unavailable_sources:
        diagnostics.append(
            "Sources de supervision non intégrées : "
            + ", ".join(unavailable_sources)
            + "."
        )

    cognitive_state = _cognitive_state_from_status(status, diagnostics)
    health_global = (
        "stable"
        if status.get("global_status") == "healthy" and not diagnostics
        else "stable_with_warning"
    )

    return {
        "identity": identity,
        "memory": memory,
        "providers": providers,
        "a2a": a2a,
        "agents": agents,
        "agent_topology": agent_topology,
        "capabilities": capabilities,
        "registered_services": registered_services,
        "goal_engine": goal_engine,
        "architecture": architecture,
        "status": status,
        "goal": goal,
        "tasks": tasks,
        "generated_at": _now_iso(),
        "runtime": runtime,
        "services": services,
        "health": {
            "realtime": status.get("global_status", "unknown"),
            "historical": "unknown",
            "global": health_global,
        },
        "health_realtime": status.get("global_status", "unknown"),
        "health_historical": "unknown",
        "health_global": health_global,
        "runtime_mode": cognitive_state["runtime_mode"],
        "active_goal": goal.get("active_goal"),
        "cognitive_state": cognitive_state,
        "diagnostics": diagnostics,
        "recommendations": recommendations,
        "last_update": time.time(),
    }


def get_self_model_status() -> dict[str, Any]:
    snapshot = build_self_model_snapshot()
    return {
        "health": snapshot["health"],
        "runtime_mode": snapshot["runtime_mode"],
        "last_update": snapshot["last_update"],
        "diagnostics": snapshot["diagnostics"],
        "status": snapshot["status"],
    }


def build_self_model_response(question: str) -> str:
    del question
    snapshot = build_self_model_snapshot()
    identity = snapshot.get("identity") or {}
    status = snapshot.get("status") or {}
    memory = snapshot.get("memory") or {}
    goal = snapshot.get("goal") or {}
    name = identity.get("name") or "Néron"
    state = snapshot.get("health", {}).get("global") or "unknown"
    memory_ok = "opérationnelle" if memory.get("ok") else "partiellement disponible"
    active_goal = goal.get("active_goal")

    goal_text = "aucun objectif actif n'est déclaré"
    if isinstance(active_goal, dict):
        goal_text = active_goal.get("title") or active_goal.get("name") or str(active_goal.get("id") or "objectif actif")
    elif active_goal:
        goal_text = str(active_goal)

    return (
        f"Je suis {name} et mon modèle interne indique un état {state}. "
        f"Je m'appuie sur Identity pour mon identité, Oblivia pour ma mémoire {memory_ok}, "
        f"Status pour mon état opérationnel ({status.get('global_status', 'unknown')}) "
        f"et Goal Runtime pour suivre le travail en cours : {goal_text}."
    )


@dataclass
class SelfModel:
    identity: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    runtime_trend: dict[str, Any] = field(default_factory=dict)
    long_term_state_memory: dict[str, Any] = field(default_factory=dict)
    self_confidence: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    performance_self_evaluation: dict[str, Any] = field(default_factory=dict)
    services: dict[str, Any] = field(default_factory=dict)
    providers: dict[str, Any] = field(default_factory=dict)
    a2a: dict[str, Any] = field(default_factory=dict)
    agents: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    goals: dict[str, Any] = field(default_factory=dict)
    architecture: dict[str, Any] = field(default_factory=dict)
    cognitive_state: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    code_awareness: dict[str, Any] = field(default_factory=dict)
    active_goal: Any = None
    health_realtime: str = "unknown"
    health_historical: str = "unknown"
    health_global: str = "unknown"
    last_update: float | None = None

    def __post_init__(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        snapshot = build_self_model_snapshot()
        self.identity = snapshot["identity"]
        self.runtime = snapshot["runtime"]
        self.services = snapshot["services"]
        self.providers = snapshot["providers"]
        self.a2a = snapshot["a2a"]
        self.agents = snapshot["agents"]
        self.memory = snapshot["memory"]
        self.goals = {
            "engine": snapshot["goal_engine"],
            "runtime": snapshot["goal"],
            "tasks": snapshot["tasks"],
        }
        self.architecture = snapshot["architecture"]
        self.capabilities = snapshot["capabilities"]
        self.cognitive_state = snapshot["cognitive_state"]
        self.diagnostics = snapshot["diagnostics"]
        self.recommendations = snapshot["recommendations"]
        self.active_goal = snapshot["active_goal"]
        self.health_realtime = snapshot["health_realtime"]
        self.health_historical = snapshot["health_historical"]
        self.health_global = snapshot["health_global"]
        self.last_update = snapshot["last_update"]

    def collect_runtime(self) -> None:
        self.refresh()

    def collect_services(self) -> None:
        self.refresh()

    def compute_health(self) -> None:
        self.refresh()

    def compute_cognitive_state(self) -> None:
        self.refresh()

    def compute_runtime_mode(self) -> None:
        self.refresh()

    def save_state(self) -> None:
        existing = _read_state()
        _write_state(existing | self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        self.identity = _safe_identity()
        data = build_self_model_snapshot()
        data.update({
            "runtime_trend": self.runtime_trend,
            "long_term_state_memory": self.long_term_state_memory,
            "self_confidence": self.self_confidence,
            "capabilities": data.get("capabilities") or self.capabilities,
            "performance_self_evaluation": self.performance_self_evaluation,
            "code_awareness": self.code_awareness,
        })
        stored = _read_state()
        for key in (
            "last_event",
            "last_intent",
            "intent_history",
            "event_count",
            "last_agent",
            "last_error",
            "agents_available",
            "last_action",
            "last_decision",
            "last_reasoning",
            "recent_activity",
            "recent_events",
        ):
            if key in stored:
                data[key] = stored[key]
        return data

    def summary(self) -> str:
        data = self.to_dict()
        runtime = data.get("runtime", {})
        cognitive = data.get("cognitive_state", {})
        diagnostics = data.get("diagnostics", [])
        recommendations = data.get("recommendations", [])
        return (
            f"Néron est {data.get('health_global')}. "
            f"CPU {runtime.get('cpu_usage')}%, RAM {runtime.get('ram_usage')}%, disque {runtime.get('disk_usage')}%.\n\n"
            "État interne de Néron :\n"
            f"- Santé globale : {data.get('health_global')}\n"
            f"- Mode runtime : {cognitive.get('runtime_mode')}\n"
            f"- Source opérationnelle : Status\n"
            f"- Diagnostics : {', '.join(diagnostics) if diagnostics else 'aucun'}\n"
            f"- Recommandations : {', '.join(recommendations) if recommendations else 'aucune'}"
        )

    def full_status_text(self) -> str:
        return self.summary()

    def update_from_event(self, event: Any) -> None:
        event_type = getattr(event, "type", None) or getattr(event, "event_type", None) or "unknown"
        source = getattr(event, "source", None) or "unknown"
        payload = getattr(event, "payload", None) or {}
        if not isinstance(payload, dict):
            payload = {"raw": str(payload)}

        data = _read_state()
        recent_events = data.get("recent_events", [])
        if not isinstance(recent_events, list):
            recent_events = []
        recent_events.append({
            "type": event_type,
            "source": source,
            "payload_keys": list(payload.keys()),
            "timestamp": time.time(),
        })

        patch: dict[str, Any] = {
            "recent_events": recent_events[-10:],
            "event_count": int(data.get("event_count", 0) or 0) + 1,
            "last_event": recent_events[-1],
        }
        if event_type == "intent.detected":
            patch["last_intent"] = {
                "intent": payload.get("intent", "unknown"),
                "confidence": payload.get("confidence") or payload.get("confidence_score"),
                "timestamp": time.time(),
            }
        if event_type in {"agent.selected", "agent.executed"}:
            patch["last_agent"] = {
                "agent": payload.get("agent") or payload.get("agent_name"),
                "timestamp": time.time(),
            }
        if "error" in payload:
            patch["last_error"] = {
                "error": payload.get("error"),
                "timestamp": time.time(),
            }
        self._merge_state(patch)

    def _merge_state(self, patch: dict[str, Any]) -> None:
        _write_state(_read_state() | patch)

    def set_last_intent(self, intent: str, confidence: Any = None) -> None:
        self._merge_state({
            "last_intent": {"intent": intent, "confidence": confidence, "timestamp": time.time()},
            "event_count": int(_read_state().get("event_count", 0) or 0) + 1,
        })

    def set_last_agent(self, agent: str | None) -> None:
        self._merge_state({"last_agent": {"agent": agent, "timestamp": time.time()}})

    def set_last_error(self, error: str | None) -> None:
        self._merge_state({"last_error": {"error": error, "timestamp": time.time()}})

    def set_agents_available(self, agents: Any) -> None:
        try:
            value = list(agents)
        except Exception:
            value = []
        self._merge_state({"agents_available": value})

    def set_last_action(self, action: str | None) -> None:
        self._merge_state({"last_action": {"action": action, "timestamp": time.time()}})

    def set_last_decision(self, decision: str | None) -> None:
        self._merge_state({"last_decision": {"decision": decision, "timestamp": time.time()}})

    def set_last_reasoning(self, reasoning: str | None) -> None:
        self._merge_state({"last_reasoning": {"reasoning": reasoning, "timestamp": time.time()}})

    def add_recent_activity(self, activity: str) -> None:
        data = _read_state()
        activities = data.get("recent_activity", [])
        if not isinstance(activities, list):
            activities = []
        activities.append({"activity": activity, "timestamp": time.time()})
        self._merge_state({"recent_activity": activities[-8:]})


def load_self_model_state() -> dict[str, Any]:
    data = _read_state()
    if data:
        return data
    model = SelfModel()
    model.save_state()
    return model.to_dict()


_SELF_MODEL: SelfModel | None = None


def get_self_model() -> SelfModel:
    global _SELF_MODEL
    if _SELF_MODEL is None:
        _SELF_MODEL = SelfModel()
    return _SELF_MODEL
