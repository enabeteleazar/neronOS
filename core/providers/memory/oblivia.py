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


    # Chaque action mémoire a son propre endpoint réel côté memory/app.py.
    # AVANT ce fix : toute action postait vers /memory/query, qui n'existe
    # pas — 404 systématique, jamais détecté faute de test de bout en bout
    # via Core avant l'audit du 19 juillet 2026.
    _ACTION_ROUTES: dict[str, tuple[str, str]] = {
        "remember": ("POST", "/memory/remember"),
        "update":   ("POST", "/memory/remember"),
        "recall":   ("POST", "/memory/recall"),
        "search":   ("POST", "/memory/recall"),
        "forget":   ("POST", "/memory/forget"),
        "observe":  ("POST", "/memory/observe"),
        "status":   ("GET", "/status"),
    }

    async def execute(
        self,
        request: ProviderRequest
    ) -> ProviderResponse:

        method, path = self._ACTION_ROUTES.get(request.action, ("POST", "/memory/recall"))

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                if method == "GET":
                    response = await client.get(f"{self.base_url}{path}")
                else:
                    response = await client.post(
                        f"{self.base_url}{path}",
                        json=request.payload,
                    )
            response.raise_for_status()

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
