from __future__ import annotations

from datetime import datetime
from threading import RLock

from .models import ProviderInfo, ProviderType, utc_now
from .protocol import ProviderProtocol


class ProviderRegistry:
    """Thread-safe in-memory registry for Kernel capability providers."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._providers: dict[str, ProviderProtocol] = {}
        self._registered_at: dict[str, datetime] = {}

    def register(self, provider: ProviderProtocol) -> ProviderInfo:
        if not provider.name:
            raise ValueError("provider name is required")
        with self._lock:
            if provider.name not in self._registered_at:
                self._registered_at[provider.name] = utc_now()
            self._providers[provider.name] = provider
            return self._info_for(provider)

    def unregister(self, name: str) -> None:
        with self._lock:
            self._providers.pop(name, None)
            self._registered_at.pop(name, None)

    def get(self, name: str) -> ProviderProtocol | None:
        with self._lock:
            return self._providers.get(name)

    def list(self) -> list[ProviderInfo]:
        with self._lock:
            return [self._info_for(provider) for provider in self._providers.values()]

    def by_type(self, provider_type: ProviderType) -> list[ProviderInfo]:
        with self._lock:
            return [
                self._info_for(provider)
                for provider in self._providers.values()
                if provider.type == provider_type
            ]

    def capabilities(self) -> list[str]:
        values: set[str] = set()
        with self._lock:
            for provider in self._providers.values():
                values.update(provider.capabilities)
        return sorted(values)

    def status(self) -> dict[str, object]:
        providers = self.list()
        by_type: dict[str, int] = {}
        by_status: dict[str, int] = {}
        serialized = [provider.model_dump(mode="json") for provider in providers]
        for provider in providers:
            by_type[provider.type] = by_type.get(provider.type, 0) + 1
            by_status[provider.status] = by_status.get(provider.status, 0) + 1

        return {
            "count": len(providers),
            "providers": serialized,
            "by_name": {provider["name"]: provider for provider in serialized},
            "types": by_type,
            "statuses": by_status,
            "capabilities": self.capabilities(),
            "memory_provider": next(
                (provider for provider in serialized if provider["type"] == "memory"),
                None,
            ),
            "llm_provider": next(
                (provider for provider in serialized if provider["type"] == "llm"),
                None,
            ),
        }

    def clear(self) -> None:
        with self._lock:
            self._providers.clear()
            self._registered_at.clear()

    def _info_for(self, provider: ProviderProtocol) -> ProviderInfo:
        registered_at = self._registered_at.get(provider.name) or utc_now()
        return ProviderInfo(
            name=provider.name,
            type=provider.type,
            status=provider.status,
            capabilities=list(provider.capabilities),
            registered_at=registered_at,
            last_seen=utc_now(),
        )


provider_registry = ProviderRegistry()
