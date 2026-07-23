"""Providers, memory, A2A and agents snapshot for the Self Model."""

from __future__ import annotations

from typing import Any


def _safe_memory_status() -> dict[str, Any]:
    try:
        from core.providers.registry import provider_registry

        providers = provider_registry.by_type("memory")
        if not providers:
            return {"ok": False, "status": "unavailable", "provider": None}
        provider = _normalize_provider(providers[0].model_dump(mode="json"))
        return {
            "ok": provider["status"] in {"healthy", "degraded"},
            "status": provider["status"],
            "provider": provider,
            "source": "provider_registry",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _safe_providers() -> dict[str, Any]:
    try:
        from core.providers.registry import provider_registry

        payload = provider_registry.status()
        providers = [
            _normalize_provider(provider)
            for provider in payload.get("providers", [])
        ]
        payload["providers"] = providers
        payload["by_name"] = {
            provider["name"]: provider for provider in providers
        }
        return payload
    except Exception as exc:
        return {"count": 0, "providers": [], "capabilities": [], "error": str(exc)}


def _safe_a2a() -> dict[str, Any]:
    try:
        from core.a2a import a2a_client

        payload = a2a_client.status()
        payload["agents"] = [
            _normalize_agent(agent, default_manager="a2a")
            for agent in payload.get("agents", [])
        ]
        return payload
    except Exception as exc:
        return {"available": False, "agent_count": 0, "agents": [], "error": str(exc)}


def _safe_agents() -> dict[str, Any]:
    try:
        from core.goal_engine import agent_registry

        agent_registry.load_existing_agents()
        payload = agent_registry.status()
        payload["agents"] = [
            _normalize_agent(agent, default_manager="agent_registry")
            for agent in payload.get("agents", [])
        ]
        return payload
    except Exception as exc:
        return {"count": 0, "available_count": 0, "agents": [], "error": str(exc)}


def _normalize_provider(provider: dict[str, Any]) -> dict[str, Any]:
    return {
        **provider,
        "kind": "provider",
        "runtime_type": "persistent",
        "managed_by": "provider_registry",
    }


def _normalize_agent(
    agent: dict[str, Any],
    *,
    default_manager: str,
) -> dict[str, Any]:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    source = str(metadata.get("source") or "")
    agent_id = str(agent.get("agent_id") or "")
    runtime_type = str(metadata.get("runtime_type") or "")
    if runtime_type not in {"persistent", "temporary", "unknown"}:
        if agent_id == "local_mock":
            runtime_type = "temporary"
        elif source in {"core_builtin", "agent_runtime"}:
            runtime_type = "persistent"
        else:
            runtime_type = "unknown"
    managed_by = str(metadata.get("managed_by") or "")
    if managed_by not in {"provider_registry", "agent_registry", "a2a", "goal", "unknown"}:
        managed_by = "goal" if source == "agent_runtime" else default_manager
    return {
        **agent,
        "kind": "agent",
        "runtime_type": runtime_type,
        "managed_by": managed_by,
    }


def _agent_topology(
    agents: dict[str, Any],
    a2a: dict[str, Any],
) -> dict[str, Any]:
    unified: dict[str, dict[str, Any]] = {}
    for source_name, collection in (
        ("agent_registry", agents.get("agents") or []),
        ("a2a", a2a.get("agents") or []),
    ):
        for item in collection:
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get("agent_id") or "")
            if not agent_id:
                continue
            current = unified.get(agent_id)
            if current is None:
                unified[agent_id] = {**item, "sources": [source_name]}
            elif source_name == "a2a":
                sources = list(dict.fromkeys([*current["sources"], source_name]))
                unified[agent_id] = {**item, "sources": sources}
            elif source_name not in current["sources"]:
                current["sources"].append(source_name)
    return {
        "count": len(unified),
        "agents": [unified[key] for key in sorted(unified)],
        "source": ["agent_registry", "a2a"],
    }
