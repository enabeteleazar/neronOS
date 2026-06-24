from __future__ import annotations

import platform
import socket
import sys
from datetime import datetime
from importlib.util import find_spec
from typing import Any
from zoneinfo import ZoneInfo

from core.modules.natural_response import try_natural_response


DEFAULT_TZ = "Europe/Paris"
STATUS_MAX_CHARS = 620
LLM_STATUS_KINDS = {"status_query"}


def _module_available(module_name: str) -> bool:
    return find_spec(module_name) is not None


def _check_goal_pipeline() -> str:
    try:
        from goal.goals.goal_orchestrator import get_goal_orchestrator  # noqa: F401

        return "available"
    except Exception:
        return "unavailable"


def _system_resources() -> dict[str, float | int | str]:
    try:
        import psutil

        return {
            "cpu_pct": round(float(psutil.cpu_percent(interval=None)), 1),
            "ram_pct": round(float(psutil.virtual_memory().percent), 1),
            "disk_pct": round(float(psutil.disk_usage("/").percent), 1),
        }
    except Exception:
        return {
            "cpu_pct": "unknown",
            "ram_pct": "unknown",
            "disk_pct": "unknown",
        }


def build_status_payload() -> dict:
    now = datetime.now(ZoneInfo(DEFAULT_TZ))

    modules = {
        "identity": "loaded" if _module_available("core.modules.identity") else "missing",
        "timer": "loaded" if _module_available("core.modules.timer") else "missing",
        "status": "loaded",
        "memory": "loaded" if _module_available("core.modules.memory") else "missing",
        "oblivia": "loaded" if _module_available("core.modules.oblivia") else "missing",
    }

    goal_pipeline = _check_goal_pipeline()

    healthy = (
        modules["identity"] == "loaded"
        and modules["timer"] == "loaded"
        and modules["status"] == "loaded"
        and modules["memory"] == "loaded"
        and modules["oblivia"] == "loaded"
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
        "services": {
            "core": "online",
            "modules": modules,
            "goal_pipeline": goal_pipeline,
        },
        "goal_pipeline": goal_pipeline,
        "llm": "unknown",
        "resources": _system_resources(),
        "health": {
            "status": "healthy" if healthy else "degraded",
            "checks": {
                "modules": modules,
                "goal_pipeline": goal_pipeline,
            },
        },
        "sources": {
            "doctor": {"status": "not_integrated"},
            "watchdog": {"status": "not_integrated"},
            "prometheus": {"status": "not_integrated"},
            "services": {"status": "local_payload"},
        },
    }


def build_status_text(payload: dict) -> str:
    return (
        "État de Néron :\n\n"
        f"- Statut global : {payload['global_status'].upper()}\n"
        f"- Core : {payload['core']}\n"
        f"- Identity : {payload['modules']['identity']}\n"
        f"- Timer : {payload['modules']['timer']}\n"
        f"- Status : {payload['modules']['status']}\n"
        f"- Memory : {payload['modules']['memory']}\n"
        f"- Oblivia : {payload['modules']['oblivia']}\n"
        f"- Goal Pipeline : {payload['goal_pipeline']}\n"
        f"- LLM : {payload['llm']}\n"
        f"- Hôte : {payload['hostname']}\n"
        f"- Python : {payload['python_version']}\n"
        f"- Timestamp : {payload['timestamp']}"
    )


def _active_services(payload: dict[str, Any]) -> list[str]:
    services = ["Core"]
    for name, state in payload.get("modules", {}).items():
        if state == "loaded":
            services.append(name.capitalize())
    if payload.get("goal_pipeline") == "available":
        services.append("Goal")
    return services


def _loaded_modules(payload: dict[str, Any]) -> list[str]:
    return [
        name.capitalize()
        for name, state in payload.get("modules", {}).items()
        if state == "loaded"
    ]


def _join_names(names: list[str]) -> str:
    if not names:
        return "aucun"
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} et {names[-1]}"


def build_status_fallback(payload: dict[str, Any], kind: str = "core_status") -> str:
    status = payload.get("global_status")
    resources = payload.get("resources") or {}
    services = _active_services(payload)

    if kind == "location_query":
        return (
            f"Je fonctionne actuellement sur l'hôte {payload.get('hostname', 'inconnu')}. "
            "Cette information provient directement du module Status."
        )

    if kind == "modules_query":
        modules = _loaded_modules(payload)
        missing = [
            name.capitalize()
            for name, state in (payload.get("modules") or {}).items()
            if state != "loaded"
        ]
        response = f"Les modules chargés sont {_join_names(modules)}."
        if payload.get("goal_pipeline") == "available":
            response += " Le pipeline Goal est disponible."
        if missing:
            response += f" Modules indisponibles : {_join_names(missing)}."
        return response

    if kind == "services_query":
        return (
            f"Mes services principaux actifs sont {_join_names(services)}. "
            "Je garde les détails techniques disponibles dans le payload de statut."
        )

    if kind == "health_query" and status == "healthy":
        return (
            "Mon système fonctionne correctement. "
            "Le Core répond, les modules principaux sont chargés et aucun problème particulier n'est détecté."
        )

    if status == "healthy":
        return (
            "Mon système fonctionne normalement. "
            "Les modules principaux sont chargés et aucun problème particulier n'est détecté."
        )

    unavailable = [
        name
        for name, state in (payload.get("modules") or {}).items()
        if state != "loaded"
    ]
    details = f" Modules concernés : {', '.join(unavailable)}." if unavailable else ""
    if resources:
        details += (
            f" Ressources observées : CPU {resources.get('cpu_pct')}%, "
            f"RAM {resources.get('ram_pct')}%, disque {resources.get('disk_pct')}%."
        )
    return f"Mon système est en état dégradé, mais le Core répond encore.{details}".strip()


async def _try_status_llm(
    *,
    question: str,
    payload: dict[str, Any],
    kind: str,
) -> str | None:
    instructions = (
        "2 à 4 phrases maximum. Résume l'état du système sans exposer le JSON, "
        "les timestamps, le hostname ou la version Python sauf si c'est indispensable."
    )
    if kind == "services_query":
        instructions = (
            "1 à 3 phrases maximum. Cite les services actifs compréhensibles par l'utilisateur, "
            "sans détailler les champs techniques."
        )
    elif kind == "modules_query":
        instructions = (
            "1 à 2 phrases maximum. Cite uniquement les modules présents dans le champ modules "
            "et le pipeline Goal si le payload indique qu'il est disponible."
        )
    elif kind == "health_query":
        instructions = (
            "1 à 3 phrases maximum. Dis si le système fonctionne correctement à partir du statut global, "
            "des modules et des ressources observées."
        )

    return await try_natural_response(
        module_name="status",
        question=question,
        facts=payload,
        instructions=instructions,
        max_chars=STATUS_MAX_CHARS,
        max_sentences=4,
        require_first_person=True,
    )


def _normalize_kind(kind: str | None) -> str:
    value = (kind or "status_query").lower()
    if value in {"core_status", "status", "system_status"}:
        return "status_query"
    if "module" in value:
        return "modules_query"
    if "service" in value:
        return "services_query"
    if "health" in value or "sante" in value:
        return "health_query"
    return value


async def build_status_response_async(
    kind: str = "core_status",
    *,
    question: str | None = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    normalized = _normalize_kind(kind)
    payload = build_status_payload()
    response = None

    if use_llm and normalized in LLM_STATUS_KINDS:
        response = await _try_status_llm(
            question=question or "Quel est ton état actuel ?",
            payload=payload,
            kind=normalized,
        )

    return {
        "response": response or build_status_fallback(payload, normalized),
        "intent": "status_query",
        "agent": "status_module",
        "confidence": "high",
        "source": "status_module",
        "status_kind": normalized,
        "status": payload,
        "raw_response": build_status_text(payload),
        "llm_used": bool(response),
    }


def build_status_response(kind: str = "core_status") -> dict:
    normalized = _normalize_kind(kind)
    payload = build_status_payload()

    return {
        "response": build_status_fallback(payload, normalized),
        "intent": "status_query",
        "agent": "status_module",
        "confidence": "high",
        "source": "status_module",
        "status_kind": normalized,
        "status": payload,
        "raw_response": build_status_text(payload),
        "llm_used": False,
    }
