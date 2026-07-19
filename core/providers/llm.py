from __future__ import annotations

import os
from typing import Any

import httpx

from core.providers.models import (
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    ProviderType,
)
from core.providers.protocol import ProviderProtocol


class ExternalLLMProvider(ProviderProtocol):
    """Provider Registry adapter for the external LLM service."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("NERON_LLM_URL") or "http://localhost:8765").rstrip("/")
        self.timeout = float(timeout or os.getenv("NERON_LLM_TIMEOUT") or 30)
        self._api_key = os.getenv("NERON_API_KEY", "")
        self._status: ProviderStatus = "unknown"

    @property
    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

    @property
    def name(self) -> str:
        return "llm"

    @property
    def type(self) -> ProviderType:
        return "llm"

    @property
    def status(self) -> ProviderStatus:
        return self._status

    @property
    def capabilities(self) -> list[str]:
        return ["llm.generate", "llm.chat"]

    async def health(self) -> ProviderResponse:
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout, 5.0)) as client:
                response = await client.get(f"{self.base_url}/health", headers=self._auth_headers)
            self._status = "healthy" if response.status_code < 500 else "degraded"
            return ProviderResponse(
                provider=self.name,
                action="health",
                status=self._status,
                result={"url": self.base_url, "status_code": response.status_code},
            )
        except Exception as exc:
            self._status = "unavailable"
            return ProviderResponse(
                provider=self.name,
                action="health",
                status="unavailable",
                error=str(exc),
            )

    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        endpoint = "generate" if request.action in {"generate", "chat"} else request.action
        payload: dict[str, Any] = {
            **request.payload,
            "action": request.action,
            "trace_id": request.trace_id,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/{endpoint}", json=payload, headers=self._auth_headers)
            response.raise_for_status()
            data = response.json()
            result = data if isinstance(data, dict) else {"text": str(data)}
            self._status = "healthy"
            return ProviderResponse(
                provider=self.name,
                action=request.action,
                status="healthy",
                result=result,
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

