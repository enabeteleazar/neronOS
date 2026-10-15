from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from core.infrastructure.event_bus import EventBus, event_bus


ServiceStatus = Literal["healthy", "degraded", "unhealthy", "unknown"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ServiceRegistration(BaseModel):
    """Strict description of a service known by the Core."""

    model_config = ConfigDict(extra="forbid", strict=True)

    service_name: str
    host: str
    port: int = Field(ge=1, le=65_535)
    version: str | None = None
    status: ServiceStatus = "unknown"
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    registered_at: datetime = Field(default_factory=_utc_now)
    last_seen: datetime = Field(default_factory=_utc_now)

    @computed_field
    @property
    def last_heartbeat(self) -> datetime:
        """Legacy read-only alias retained for existing Registry consumers."""

        return self.last_seen

    @field_validator("service_name", "host")
    @classmethod
    def require_non_empty_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value

    @field_validator("version")
    @classmethod
    def reject_empty_version(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("version must not be empty")
        return value

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("capabilities must not contain empty values")
        if len(values) != len(set(values)):
            raise ValueError("capabilities must be unique")
        return values

    @field_validator("registered_at", "last_seen")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("timestamp must be UTC")
        return value


class ServiceRegistry:
    """Thread-safe catalogue of services communicating through Core."""

    def __init__(self, bus: EventBus | None = None) -> None:
        self._services: dict[str, ServiceRegistration] = {}
        self._lock = RLock()
        self._event_bus = bus

    def register(
        self,
        service: ServiceRegistration | None = None,
        *,
        service_name: str | None = None,
        host: str | None = None,
        port: int | None = None,
        version: str | None = None,
        status: ServiceStatus = "unknown",
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register a validated model, while accepting the legacy keyword API."""

        if service is not None and any(
            value is not None
            for value in (service_name, host, port, version, capabilities, metadata)
        ):
            raise ValueError("service model cannot be combined with registration fields")
        if service is None:
            service = ServiceRegistration(
                service_name=service_name,
                host=host,
                port=port,
                version=version,
                status=status,
                capabilities=capabilities or [],
                metadata=metadata or {},
            )
        elif not isinstance(service, ServiceRegistration):
            raise TypeError("service must be a ServiceRegistration")

        stored = service.model_copy(deep=True)
        with self._lock:
            self._services[stored.service_name] = stored
        result = self._serialize(stored)
        self._publish("registry.service_registered", stored)
        return result

    def heartbeat(
        self,
        service_name: str,
        status: ServiceStatus | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if status not in (None, "healthy", "degraded", "unhealthy", "unknown"):
            raise ValueError("invalid service status")
        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError("metadata must be a dictionary")

        with self._lock:
            current = self._services.get(service_name)
            if current is None:
                return None
            updated_metadata = deepcopy(current.metadata)
            if metadata is not None:
                updated_metadata.update(deepcopy(metadata))
            updated = current.model_copy(
                update={
                    "last_seen": _utc_now(),
                    "status": status if status is not None else current.status,
                    "metadata": updated_metadata,
                },
                deep=True,
            )
            self._services[service_name] = updated
        result = self._serialize(updated)
        self._publish("registry.service_heartbeat", updated)
        return result

    def unregister(self, service_name: str) -> dict[str, Any] | None:
        with self._lock:
            service = self._services.pop(service_name, None)
        if service is None:
            return None
        result = self._serialize(service)
        self._publish("registry.service_unregistered", service)
        return result

    def get_service(self, service_name: str) -> dict[str, Any] | None:
        with self._lock:
            service = self._services.get(service_name)
            return self._serialize(service) if service is not None else None

    def list_services(
        self,
        status: ServiceStatus | None = None,
        capability: str | None = None,
    ) -> list[dict[str, Any]]:
        if status not in (None, "healthy", "degraded", "unhealthy", "unknown"):
            raise ValueError("invalid service status")
        with self._lock:
            services = [
                service
                for service in self._services.values()
                if (status is None or service.status == status)
                and (capability is None or capability in service.capabilities)
            ]
            return [self._serialize(service) for service in services]

    def mark_stale_services(self, timeout_seconds: float) -> list[dict[str, Any]]:
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds cannot be negative")
        cutoff = _utc_now() - timedelta(seconds=timeout_seconds)
        stale: list[ServiceRegistration] = []
        with self._lock:
            for name, service in self._services.items():
                if service.last_seen < cutoff and service.status != "unhealthy":
                    updated = service.model_copy(update={"status": "unhealthy"}, deep=True)
                    self._services[name] = updated
                    stale.append(updated)
        for service in stale:
            self._publish("registry.service_stale", service, level="warning")
        return [self._serialize(service) for service in stale]

    def clear(self) -> None:
        with self._lock:
            self._services.clear()

    def status(self) -> dict[str, Any]:
        with self._lock:
            names = sorted(self._services)
        return {"service_count": len(names), "services": names}

    def _publish(
        self,
        event_type: str,
        service: ServiceRegistration,
        *,
        level: Literal["info", "warning", "error"] = "info",
    ) -> None:
        if self._event_bus is None:
            return
        self._event_bus.publish(
            event_type=event_type,
            source="core.service_registry",
            target=service.service_name,
            payload={
                "service_name": service.service_name,
                "status": service.status,
            },
            level=level,
        )

    @staticmethod
    def _serialize(service: ServiceRegistration) -> dict[str, Any]:
        return deepcopy(service.model_dump(mode="json"))


service_registry = ServiceRegistry(event_bus)
