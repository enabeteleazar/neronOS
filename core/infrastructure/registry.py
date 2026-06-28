from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ServiceRegistry:
    """Process-local registry of services that communicate through Core."""

    def __init__(self) -> None:
        self._services: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def register(
        self,
        service_name: str,
        host: str,
        port: int,
        version: str | None = None,
    ) -> dict[str, Any]:
        if not service_name.strip():
            raise ValueError("service_name is required")
        if not host.strip():
            raise ValueError("host is required")
        if not 1 <= port <= 65_535:
            raise ValueError("port must be between 1 and 65535")

        timestamp = _utc_now()
        service = {
            "service_name": service_name,
            "host": host,
            "port": port,
            "version": version,
            "registered_at": timestamp,
            "last_heartbeat": timestamp,
            "status": "online",
        }
        with self._lock:
            self._services[service_name] = service
        return deepcopy(service)

    def heartbeat(self, service_name: str) -> dict[str, Any] | None:
        with self._lock:
            service = self._services.get(service_name)
            if service is None:
                return None
            service["last_heartbeat"] = _utc_now()
            service["status"] = "online"
            return deepcopy(service)

    def list_services(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(list(self._services.values()))

    def get_service(self, service_name: str) -> dict[str, Any] | None:
        with self._lock:
            service = self._services.get(service_name)
            return deepcopy(service) if service is not None else None

    def clear(self) -> None:
        with self._lock:
            self._services.clear()

    def status(self) -> dict[str, Any]:
        with self._lock:
            names = sorted(self._services)
        return {"service_count": len(names), "services": names}


service_registry = ServiceRegistry()
