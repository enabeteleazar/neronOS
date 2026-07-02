from __future__ import annotations

from typing import Any

from memory.oblivia import MemoryQuery, MemoryRecord, ObliviaMemoryManager

from ..models import ProviderRequest, ProviderResponse, ProviderStatus, ProviderType
from ..protocol import ProviderProtocol


class ObliviaProvider(ProviderProtocol):
    """Memory provider bridge over the existing Oblivia manager."""

    def __init__(self, manager: ObliviaMemoryManager | None = None) -> None:
        self._manager = manager or ObliviaMemoryManager()
        self._status: ProviderStatus = "healthy"

    @property
    def name(self) -> str:
        return "oblivia"

    @property
    def type(self) -> ProviderType:
        return "memory"

    @property
    def status(self) -> ProviderStatus:
        return self._status

    @property
    def capabilities(self) -> list[str]:
        return [
            "health",
            "remember",
            "recall",
            "search",
            "forget",
            "update",
            "recent",
            "cleanup",
            "status",
        ]

    async def health(self) -> ProviderResponse:
        return await self.execute(ProviderRequest(action="health"))

    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        action = request.action.strip().lower()
        try:
            if action in {"health", "status"}:
                result = self._manager.status()
                self._status = "healthy" if getattr(result, "ok", False) else "degraded"
                return self._response(request, result=self._dump(result))

            if action in {"remember", "update"}:
                payload = request.payload
                record = MemoryRecord(
                    source=payload.get("source", "memory_manager"),
                    category=payload.get("category", "unknown"),
                    content=str(payload.get("content") or payload.get("text") or ""),
                    metadata=payload.get("metadata") or {},
                )
                saved = self._manager.remember(record)
                return self._response(request, result=self._dump(saved))

            if action == "recall":
                payload = request.payload
                query = MemoryQuery(
                    query=str(payload.get("query") or payload.get("text") or ""),
                    category=payload.get("category"),
                    limit=int(payload.get("limit") or 10),
                )
                knowledge = self._manager.recall_knowledge(
                    query.query,
                    limit=query.limit,
                )
                return self._response(request, result={
                    **knowledge,
                    "results": [
                        self._dump(item) for item in self._manager.recall(query)
                    ],
                })

            if action == "search":
                payload = request.payload
                query = str(payload.get("query") or payload.get("text") or "")
                limit = int(payload.get("limit") or 10)
                return self._response(
                    request,
                    result=[self._dump(item) for item in self._manager.search(query, limit=limit)],
                )

            if action == "forget":
                payload = request.payload
                query = str(payload.get("query") or payload.get("text") or "")
                if not query.strip():
                    raise ValueError("forget query is required")
                return self._response(
                    request,
                    result=self._manager.forget(query),
                )

            if action == "recent":
                limit = int(request.payload.get("limit") or 10)
                return self._response(
                    request,
                    result=[
                        self._dump(item)
                        for item in self._manager.recent(limit)
                    ],
                )

            if action == "cleanup":
                days = max(1, int(request.payload.get("days") or 30))
                return self._response(
                    request,
                    result=self._manager.cleanup(days),
                )

            return self._response(
                request,
                status="unhealthy",
                error=f"unsupported memory provider action: {request.action}",
            )
        except Exception as exc:
            self._status = "degraded"
            return self._response(request, status="degraded", error=str(exc))

    def _response(
        self,
        request: ProviderRequest,
        *,
        result: Any = None,
        status: ProviderStatus | None = None,
        error: str | None = None,
    ) -> ProviderResponse:
        return ProviderResponse(
            provider=self.name,
            action=request.action,
            status=status or self._status,
            result=result,
            error=error,
            trace_id=request.trace_id,
        )

    @staticmethod
    def _dump(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value
