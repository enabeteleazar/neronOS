from __future__ import annotations

import platform
import socket
import sys
from datetime import datetime
from importlib.util import find_spec
from zoneinfo import ZoneInfo


DEFAULT_TZ = "Europe/Paris"


def _module_available(module_name: str) -> bool:
    return find_spec(module_name) is not None


def _check_goal_pipeline() -> str:
    try:
        from goal.goals.goal_orchestrator import get_goal_orchestrator  # noqa: F401

        return "available"
    except Exception:
        return "unavailable"


def build_status_payload() -> dict:
    now = datetime.now(ZoneInfo(DEFAULT_TZ))

    modules = {
        "identity": "loaded" if _module_available("core.modules.identity") else "missing",
        "timer": "loaded" if _module_available("core.modules.timer") else "missing",
        "status": "loaded",
    }

    goal_pipeline = _check_goal_pipeline()

    healthy = (
        modules["identity"] == "loaded"
        and modules["timer"] == "loaded"
        and modules["status"] == "loaded"
        and goal_pipeline == "available"
    )

    return {
        "global_status": "healthy" if healthy else "degraded",
        "timestamp": now.isoformat(),
        "hostname": socket.gethostname(),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "core": "online",
        "modules": modules,
        "goal_pipeline": goal_pipeline,
        "llm": "unknown",
    }


def build_status_text(payload: dict) -> str:
    return (
        "État de Néron :\n\n"
        f"- Statut global : {payload['global_status'].upper()}\n"
        f"- Core : {payload['core']}\n"
        f"- Identity : {payload['modules']['identity']}\n"
        f"- Timer : {payload['modules']['timer']}\n"
        f"- Status : {payload['modules']['status']}\n"
        f"- Goal Pipeline : {payload['goal_pipeline']}\n"
        f"- LLM : {payload['llm']}\n"
        f"- Hôte : {payload['hostname']}\n"
        f"- Python : {payload['python_version']}\n"
        f"- Timestamp : {payload['timestamp']}"
    )


def build_status_response(kind: str = "core_status") -> dict:
    payload = build_status_payload()

    return {
        "response": build_status_text(payload),
        "intent": "status_query",
        "agent": "status_module",
        "confidence": "high",
        "source": "status_module",
        "status_kind": kind,
        "status": payload,
    }
