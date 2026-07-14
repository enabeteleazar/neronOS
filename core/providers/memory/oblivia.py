from __future__ import annotations

import os
import httpx

from core.providers.protocol import ProviderProtocol
from core.providers.models import (
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    ProviderType,
)


class ObliviaProvider(ProviderProtocol):
    """
    Remote Memory Provider.

    Le Core ne possède pas la mémoire.
    Memory est un service externe sur server4.
    """

    def __init__(self):
        self.base_url = os.getenv(
            "NERON_MEMORY_URL",
            "http://127.0.1.4:8040"
        )

        self._status: ProviderStatus = "unknown"


    @property
    def name(self) -> str:
        return "oblivia-memory"


    @property
    def type(self) -> ProviderType:
        return "memory"


    @property
    def status(self) -> ProviderStatus:
        return self._status


    @property
    def capabilities(self) -> list[str]:
        return [
            "memory.read",
            "memory.write",
            "memory.search",
        ]


    async def health(self) -> ProviderResponse:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.get(
                    f"{self.base_url}/health"
                )

            if response.status_code == 200:
                self._status = "healthy"

                return ProviderResponse(
                    provider=self.name,
                    action="health",
                    status="healthy",
                    result={
                        "url": self.base_url
                    },
                )

        except Exception as exc:
            self._status = "unavailable"

            return ProviderResponse(
                provider=self.name,
                action="health",
                status="unavailable",
                error=str(exc),
            )

        self._status = "unhealthy"

        return ProviderResponse(
            provider=self.name,
            action="health",
            status="unhealthy",
        )


    async def execute(
        self,
        request: ProviderRequest
    ) -> ProviderResponse:

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{self.base_url}/memory/query",
                    json=request.model_dump()
                )

            self._status = "healthy"

            return ProviderResponse(
                provider=self.name,
                action=request.action,
                status="healthy",
                result=response.json(),
                trace_id=request.trace_id,
            )

        except Exception as exc:
            self._status = "unavailable"

            return ProviderResponse(
                provider=self.name,
                action=request.action,
                status="unavailable",
                error=str(exc),
                trace_id=request.trace_id,
            )
