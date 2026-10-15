from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.infrastructure.registry import ServiceRegistry


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _service_view(service: dict[str, Any], now: datetime) -> dict[str, Any]:
    last_seen = _parse_utc(service["last_seen"])
    return {
        "name": service["service_name"],
        "status": service["status"],
        "host": service["host"],
        "port": service["port"],
        "capabilities": list(service.get("capabilities", [])),
        "registered_at": service["registered_at"],
        "last_seen": service["last_seen"],
        "age_seconds": max(0, int((now - last_seen).total_seconds())),
    }


def build_topology(registry: ServiceRegistry) -> dict[str, Any]:
    """Build a read-only ecosystem view from the canonical Registry."""

    now = datetime.now(timezone.utc)
    services = sorted(
        (
            _service_view(service, now)
            for service in registry.list_services()
        ),
        key=lambda service: service["name"],
    )
    healthy_count = sum(
        service["status"] == "healthy" for service in services
    )
    degraded_count = sum(
        service["status"] == "degraded" for service in services
    )
    offline_count = sum(
        service["status"] in {"unhealthy", "unknown"}
        for service in services
    )

    if not services or offline_count:
        status = "unhealthy"
    elif degraded_count:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "service_count": len(services),
        "healthy_count": healthy_count,
        "degraded_count": degraded_count,
        "offline_count": offline_count,
        "generated_at": now.isoformat(),
        "services": services,
    }


def get_topology_service(
    registry: ServiceRegistry,
    service_name: str,
) -> dict[str, Any] | None:
    topology = build_topology(registry)
    return next(
        (
            service
            for service in topology["services"]
            if service["name"] == service_name
        ),
        None,
    )


def service_ecosystem_context(registry: ServiceRegistry) -> dict[str, Any]:
    """Facts ready for future natural-language status responses."""

    topology = build_topology(registry)
    active = [
        service["name"]
        for service in topology["services"]
        if service["status"] in {"healthy", "degraded"}
    ]
    unavailable = [
        service["name"]
        for service in topology["services"]
        if service["status"] in {"unhealthy", "unknown"}
    ]
    return {
        "status": topology["status"],
        "service_count": topology["service_count"],
        "active_service_count": len(active),
        "active_services": active,
        "unavailable_services": unavailable,
        "healthy_count": topology["healthy_count"],
        "degraded_count": topology["degraded_count"],
        "offline_count": topology["offline_count"],
    }
