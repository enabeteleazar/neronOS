from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from core.identity import get_identity
from core.modules.status.service import build_status_payload


DEFAULT_TZ = "Europe/Paris"
STATE_PATH = Path("/etc/neron/data/self_model_state.json")


def _now_iso() -> str:
    return datetime.now(ZoneInfo(DEFAULT_TZ)).isoformat()


def _read_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(data: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _safe_identity() -> dict[str, Any]:
    try:
        return dict(get_identity())
    except Exception as exc:
        return {"name": "Néron", "status": "unavailable", "error": str(exc)}


def _safe_memory_status() -> dict[str, Any]:
    try:
        from core.modules.oblivia.manager import ObliviaMemoryManager

        status = ObliviaMemoryManager().status()
        if hasattr(status, "model_dump"):
            return status.model_dump()
        if hasattr(status, "dict"):
            return status.dict()
        return dict(status)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _safe_goal_runtime() -> dict[str, Any]:
    goal: dict[str, Any] | None = None
    runtime_status: dict[str, Any] | None = None

    try:
        from goal.goals.goal_manager import get_goal_manager

        goal = get_goal_manager().get_active_goal()
    except Exception:
        goal = None

    goal_id = None
    if isinstance(goal, dict):
        goal_id = goal.get("id") or goal.get("goal_id")

    if goal_id:
        try:
            from goal.goals.execution_engine import get_goal_execution_engine

            runtime_status = get_goal_execution_engine().get_goal_status(str(goal_id))
        except Exception as exc:
            runtime_status = {"error": str(exc)}

    return {
        "active_goal": goal,
        "runtime_status": runtime_status,
    }


def _runtime_from_status(status: dict[str, Any]) -> dict[str, Any]:
    resources = status.get("resources") or {}
    return {
        "cpu_usage": resources.get("cpu_pct"),
        "ram_usage": resources.get("ram_pct"),
        "disk_usage": resources.get("disk_pct"),
        "source": "status_module",
    }


def _services_from_status(status: dict[str, Any]) -> dict[str, Any]:
    modules = status.get("modules") or {}
    items = {"core": status.get("core", "unknown")}
    items.update({f"module:{name}": state for name, state in modules.items()})
    items["goal_pipeline"] = status.get("goal_pipeline", "unknown")

    active = [name for name, state in items.items() if state in {"online", "loaded", "available"}]
    inactive = [name for name, state in items.items() if name not in active]

    return {
        "items": items,
        "summary": {
            "total": len(items),
            "active": len(active),
            "inactive": len(inactive),
            "all_active": len(inactive) == 0,
        },
    }


def _cognitive_state_from_status(status: dict[str, Any]) -> dict[str, Any]:
    healthy = status.get("global_status") == "healthy"
    state = "stable" if healthy else "warning"
    runtime_mode = "normal" if healthy else "prudent"
    severity_score = 0 if healthy else 45
    return {
        "state": state,
        "severity_score": severity_score,
        "primary_issue": None if healthy else "status_degraded",
        "runtime_pressure": "normal" if healthy else "moderate",
        "autonomy_available": healthy,
        "degraded_mode": not healthy,
        "critical_services_ok": healthy,
        "runtime_mode": runtime_mode,
        "planner_enabled": True,
        "heavy_reasoning_allowed": healthy,
        "autonomous_actions_allowed": True,
        "max_parallel_agents": 3 if healthy else 1,
        "source": "status_module",
    }


def build_self_model_snapshot() -> dict[str, Any]:
    status = build_status_payload()
    memory = _safe_memory_status()
    goal = _safe_goal_runtime()
    identity = _safe_identity()
    runtime = _runtime_from_status(status)
    services = _services_from_status(status)
    cognitive_state = _cognitive_state_from_status(status)
    health_global = "stable" if status.get("global_status") == "healthy" else "stable_with_warning"

    return {
        "identity": identity,
        "memory": memory,
        "status": status,
        "goal": goal,
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
        "diagnostics": [] if status.get("global_status") == "healthy" else ["Status opérationnel dégradé."],
        "recommendations": [] if status.get("global_status") == "healthy" else ["Consulter le module Status avant une action lourde."],
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
            "capabilities": self.capabilities,
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
