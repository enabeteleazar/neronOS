"""Routes /self-model : état de Néron pour le Dashboard et les clients.

Rétablies depuis septembre (9728e2b), perdues avec 58ab382 qui n'avait gardé
que /self-model et /self-model/summary. Appels connus :
  - Dashboard : GET /self-model, GET /self-model/agents,
    POST /self-model/agents/{id}/status, POST /self-model/homelab/slots/{id} ;
  - neronClient : GET /self-model/context (lit `identity`).

Adaptées à la séparation Core/Goal et aux serveurs distincts : rien n'est
importé de Goal. Ses tâches et ses agents sont lus, et l'état des agents
modifié, par HTTP (GoalClient), avec un délai court et sans bloquer la
réponse si Goal est injoignable.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.identity import get_identity
from core.modules.self_model import build_self_model_response, get_self_model

logger = logging.getLogger("core.api.self_model")

_GOAL_TIMEOUT = 2.0

router = APIRouter(
    prefix="/self-model",
    tags=["self-model"],
)


def _snapshot_sync() -> dict:
    model = get_self_model()
    model.refresh()
    return model.to_dict()


async def _snapshot() -> dict:
    # Délègue à un thread : le snapshot finit par appeler subprocess.run()
    # (systemctl, jusqu'à 5 s x2) via services_snapshot(). Exécuté en direct
    # dans une route async, il gelait TOUT l'event loop du Core — le
    # Dashboard interroge /self-model toutes les 2 s.
    return await asyncio.to_thread(_snapshot_sync)


async def _from_goal(call: str, *args: Any) -> Any:
    """Appel GoalClient borné ; None si Goal est lent ou injoignable."""
    from server.common.goal_client import get_goal_client

    try:
        return await asyncio.wait_for(getattr(get_goal_client(), call)(*args), _GOAL_TIMEOUT)
    except Exception as exc:
        logger.warning("self_model_goal_unavailable call=%s error=%s", call, exc)
        return None


@router.get("")
async def self_model_state() -> dict:
    return await _snapshot()


@router.get("/summary")
async def self_model_summary() -> dict:
    data = await _snapshot()
    return {
        "summary": build_self_model_response("Que sais-tu de toi-même ?"),
        "state": data,
    }


@router.get("/status")
async def self_model_status() -> dict:
    data = await _snapshot()
    return {
        "health": data["health"],
        "runtime_mode": data["runtime_mode"],
        "runtime": data["runtime"],
        "diagnostics": data["diagnostics"],
        "recommendations": data["recommendations"],
        "generated_at": data["generated_at"],
    }


def _code_awareness() -> dict[str, Any]:
    try:
        from modules.code_awareness.scanner import scan_project

        code_scan = scan_project(max_depth=1)
        return {
            "modules": code_scan.get("modules", 0),
            "files": code_scan.get("files", 0),
            "last_scan": None,
            "architecture_known": True,
        }
    except Exception:
        return {"modules": 0, "files": 0, "last_scan": None, "architecture_known": False}


@router.get("/context")
async def self_model_context() -> dict:
    data, task_summary, next_task = await asyncio.gather(
        _snapshot(),
        _from_goal("get_task_summary"),
        _from_goal("get_next_task"),
    )
    tasks = data.get("tasks") or {}
    return {
        "identity": get_identity(),
        "memory": data.get("memory", {}),
        "status": data.get("status", {}),
        "health": {
            "realtime": data.get("health_realtime"),
            "historical": data.get("health_historical"),
            "global": data.get("health_global"),
        },
        "goal": data.get("goal", {"active_goal": data.get("active_goal")}),
        "tasks": {
            "summary": task_summary if task_summary is not None else tasks.get("summary"),
            "next": next_task,
            "managed_by": "manager_de_chantier",
            "source": "goal_http" if task_summary is not None else "unavailable",
        },
        "diagnostics": data.get("diagnostics", []),
        "recommendations": data.get("recommendations", []),
        "summary": data.get("cognitive_summary"),
        "runtime": data.get("runtime", {}) or {},
        "runtime_trend": data.get("runtime_trend", {}),
        "long_term_state_memory": data.get("long_term_state_memory", {}),
        "self_confidence": data.get("self_confidence", {}),
        "capabilities": data.get("capabilities", {}),
        "performance_self_evaluation": data.get("performance_self_evaluation", {}),
        "services": data.get("services", {}),
        "code_awareness": await asyncio.to_thread(_code_awareness),
        "cognitive_state": data.get("cognitive_state", {}),
        "last_activity": {
            "last_event": data.get("last_event"),
            "last_intent": data.get("last_intent"),
            "last_agent": data.get("last_agent"),
        },
    }


@router.get("/identity")
async def identity() -> dict:
    return (await _snapshot())["identity"]


@router.get("/capabilities")
async def capabilities() -> dict:
    return (await _snapshot())["capabilities"]


@router.get("/providers")
async def providers() -> dict:
    return (await _snapshot())["providers"]


@router.get("/services")
async def services() -> dict:
    return (await _snapshot())["registered_services"]


def _goal_agent_entries(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    disabled = set(payload.get("disabled") or [])
    return [
        {
            "agent_id": str(name),
            "name": str(name),
            "status": "unavailable" if name in disabled else "available",
            "description": "",
            "sources": ["goal"],
            "managed_by": "manager_de_chantier",
        }
        for name in payload.get("agents") or []
    ]


@router.get("/agents")
async def agents() -> dict:
    """Agents A2A (Core) + agents générés par Goal, lus en HTTP.

    Le Dashboard affiche `agents` (agent_id, status, description) et active
    ou désactive chacun via POST /self-model/agents/{id}/status.
    """
    data, goal_payload = await asyncio.gather(_snapshot(), _from_goal("list_agents"))
    topology = data["agent_topology"]
    known = {item.get("agent_id") for item in topology.get("agents", [])}
    goal_agents = [a for a in _goal_agent_entries(goal_payload) if a["agent_id"] not in known]
    return {
        **topology,
        "agents": [*topology.get("agents", []), *goal_agents],
        "count": topology.get("count", 0) + len(goal_agents),
        "registry": data["agents"],
        "a2a": data["a2a"],
        "goal": {"reachable": goal_payload is not None, "count": len(goal_agents)},
    }


@router.get("/memory")
async def memory() -> dict:
    return (await _snapshot())["memory"]


@router.get("/goals")
async def goals() -> dict:
    data = await _snapshot()
    return {
        "engine": data["goal_engine"],
        "runtime": data["goal"],
        "tasks": data["tasks"],
    }


@router.get("/architecture")
async def architecture() -> dict:
    return (await _snapshot())["architecture"]


# ── Écriture ────────────────────────────────────────────────────────────────


class SetSlotBody(BaseModel):
    catalog_id: str | None = None


@router.post("/homelab/slots/{unit_id}")
async def set_slot(unit_id: str, body: SetSlotBody) -> dict:
    from core.modules.self_model.homelab import set_homelab_slot

    try:
        slots = set_homelab_slot(unit_id, body.catalog_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"slots": slots}


class SetAgentStatusBody(BaseModel):
    enabled: bool


@router.post("/agents/{agent_id}/status")
async def set_agent_status(agent_id: str, body: SetAgentStatusBody) -> dict:
    """Active ou désactive un agent généré, par l'API HTTP de Goal.

    Septembre modifiait un registre en mémoire du Core (sans effet réel ni
    persistance) ; l'état vit désormais côté Goal (agents_state.json).
    """
    from server.common.goal_client import GoalClientError, get_goal_client

    try:
        result = await get_goal_client().set_agent_enabled(agent_id, body.enabled)
    except GoalClientError as exc:
        raise HTTPException(status_code=503, detail=f"Goal injoignable : {exc}") from exc

    status = result.get("status")
    if status == "not_found":
        raise HTTPException(status_code=404, detail=f"agent inconnu : {agent_id}")
    if status == "refused":
        raise HTTPException(status_code=403, detail=f"agent protégé : {agent_id}")
    if status not in {"enabled", "disabled"}:
        raise HTTPException(status_code=502, detail=f"réponse inattendue de Goal : {status}")
    return {
        "agent_id": result.get("agent", agent_id),
        "status": "available" if result.get("enabled") else "unavailable",
    }
