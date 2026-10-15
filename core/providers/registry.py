from __future__ import annotations

from datetime import datetime
from threading import RLock

from .models import ProviderInfo, ProviderRequest, ProviderResponse, ProviderType, utc_now
from .protocol import ProviderProtocol


class ProviderRegistry:
    """Thread-safe in-memory registry for Kernel capability providers."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._providers: dict[str, ProviderProtocol] = {}
        self._registered_at: dict[str, datetime] = {}
        self._a2a_client = None

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

    async def execute_via_a2a(
        self,
        name: str,
        request: ProviderRequest,
        *,
        client=None,
    ) -> ProviderResponse:
        """Execute a provider capability through the internal A2A protocol."""
        from core.a2a import A2AClient, AgentCard, AgentTask

        provider = self.get(name)
        if provider is None:
            return ProviderResponse(
                provider=name,
                action=request.action,
                status="unavailable",
                error="provider not found",
                trace_id=request.trace_id,
            )

        if client is None and self._a2a_client is None:
            self._a2a_client = A2AClient()
        transport: A2AClient = client or self._a2a_client
        agent_id = f"provider:{provider.name}"
        card = AgentCard(
            agent_id=agent_id,
            name=f"{provider.name} provider",
            capabilities=list(provider.capabilities),
            description=f"A2A adapter for the {provider.type} provider",
            tags=["provider", str(provider.type)],
            metadata={
                "kind": "provider",
                "provider_name": provider.name,
                "provider_type": provider.type,
            },
            status="available",
        )

        async def handler(task: AgentTask):
            provider_request = ProviderRequest.model_validate(
                task.payload["provider_request"]
            )
            provider_response = await provider.execute(provider_request)
            return {
                "provider_response": provider_response.model_dump(mode="json")
            }

        transport.register_handler(card, handler)
        task_response = await transport.send_task(
            AgentTask(
                target_agent=agent_id,
                payload={
                    "provider_request": request.model_dump(mode="json"),
                },
                trace_id=request.trace_id,
            )
        )
        if task_response.status == "failed":
            return ProviderResponse(
                provider=name,
                action=request.action,
                status="unavailable",
                error=task_response.error or "A2A provider execution failed",
                trace_id=request.trace_id,
            )
        return ProviderResponse.model_validate(
            task_response.result["provider_response"]
        )

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
            self._a2a_client = None

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
