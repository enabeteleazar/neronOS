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


class ObsidianKnowledgeProvider(ProviderProtocol):
    """
    Remote Knowledge Provider.

    Le Core ne possède pas la base de connaissances. Obsidian est exposé
    par le service memory (server/memory/knowledge/), sous /knowledge/*,
    volontairement séparé de /memory/* : un document consulté n'est pas un
    souvenir personnel (cf. server/memory/protocols.py).

    Contrairement à ObliviaProvider, ces routes sont des GET avec
    paramètres de requête, pas des POST JSON — reflète fidèlement l'API
    réelle de memory/app.py.
    """

    _ACTION_ROUTES: dict[str, str] = {
        "query": "/knowledge/query",
        "documents": "/knowledge/documents",
        "status": "/knowledge/health",
    }

    def __init__(self):
        self.base_url = os.getenv(
            "NERON_MEMORY_URL",
            "http://127.0.1.4:8040"
        )
        self._status: ProviderStatus = "unknown"

    @property
    def name(self) -> str:
        return "obsidian-knowledge"

    @property
    def type(self) -> ProviderType:
        return "knowledge"

    @property
    def status(self) -> ProviderStatus:
        return self._status

    @property
    def capabilities(self) -> list[str]:
        return [
            "knowledge.query",
            "knowledge.list",
        ]

    async def health(self) -> ProviderResponse:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.get(f"{self.base_url}/knowledge/health")

            if response.status_code == 200:
                self._status = "healthy"
                return ProviderResponse(
                    provider=self.name,
                    action="health",
                    status="healthy",
                    result={"url": self.base_url},
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
        path = self._ACTION_ROUTES.get(request.action, "/knowledge/query")

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                if request.action == "documents" or request.action == "status":
                    response = await client.get(f"{self.base_url}{path}")
                else:
                    params = {
                        "q": request.payload.get("query", ""),
                        "limit": request.payload.get("limit", 10),
                    }
                    response = await client.get(f"{self.base_url}{path}", params=params)
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
