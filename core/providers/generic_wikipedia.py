"""
Provider Wikipédia pour le Kernel Néron.

Type "knowledge" (déjà présent dans ProviderType). Implémente ProviderProtocol
pour s'enregistrer dans provider_registry aux côtés du provider mémoire.

Action supportée : "search" — payload {"query": <nom ou sujet>}.
"""

from __future__ import annotations

import httpx

from .models import ProviderRequest, ProviderResponse, ProviderStatus, ProviderType

_SEARCH_URL = "https://fr.wikipedia.org/w/api.php"
_SUMMARY_URL = "https://fr.wikipedia.org/api/rest_v1/page/summary/{title}"
_USER_AGENT = "NeronOS/1.0 (identity-lookup provider; contact: homebox)"
_TIMEOUT = httpx.Timeout(5.0, connect=3.0)


class WikipediaProvider:
    """Provider de recherche d'identité via l'API REST Wikipédia (fr)."""

    def __init__(self) -> None:
        self._status: ProviderStatus = "unknown"

    @property
    def name(self) -> str:
        return "wikipedia"

    @property
    def type(self) -> ProviderType:
        return "generic"

    @property
    def status(self) -> ProviderStatus:
        return self._status

    @property
    def capabilities(self) -> list[str]:
        return ["identity_lookup", "search"]

    async def health(self) -> ProviderResponse:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.get(
                    _SEARCH_URL,
                    params={"action": "query", "meta": "siteinfo", "format": "json"},
                    headers={"User-Agent": _USER_AGENT},
                )
                response.raise_for_status()
            self._status = "healthy"
            return ProviderResponse(
                provider=self.name, action="health", status="healthy", result={"ok": True}
            )
        except httpx.HTTPError as exc:
            self._status = "unhealthy"
            return ProviderResponse(
                provider=self.name, action="health", status="unhealthy", error=str(exc)
            )

    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        if request.action != "search":
            return ProviderResponse(
                provider=self.name,
                action=request.action,
                status="unavailable",
                error=f"unsupported action: {request.action}",
                trace_id=request.trace_id,
            )

        query = str(request.payload.get("query") or "").strip()
        if not query:
            return ProviderResponse(
                provider=self.name,
                action=request.action,
                status="unavailable",
                error="empty query",
                trace_id=request.trace_id,
            )

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
                search_response = await client.get(
                    _SEARCH_URL,
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": query,
                        "srlimit": 5,
                        "format": "json",
                    },
                )
                search_response.raise_for_status()
                search_hits = search_response.json().get("query", {}).get("search", [])

                if not search_hits:
                    self._status = "healthy"
                    return ProviderResponse(
                        provider=self.name,
                        action=request.action,
                        status="healthy",
                        result={
                            "found": False,
                            "title": None,
                            "summary": None,
                            "url": None,
                            "candidate_count": 0,
                        },
                        trace_id=request.trace_id,
                    )

                top_title = search_hits[0]["title"]
                summary_response = await client.get(
                    _SUMMARY_URL.format(title=top_title.replace(" ", "_"))
                )
                summary_response.raise_for_status()
                summary_data = summary_response.json()

            self._status = "healthy"
            return ProviderResponse(
                provider=self.name,
                action=request.action,
                status="healthy",
                result={
                    "found": True,
                    "title": summary_data.get("title", top_title),
                    "summary": summary_data.get("extract"),
                    "url": summary_data.get("content_urls", {}).get("desktop", {}).get("page"),
                    "candidate_count": len(search_hits),
                },
                trace_id=request.trace_id,
            )
        except httpx.HTTPError as exc:
            self._status = "degraded"
            return ProviderResponse(
                provider=self.name,
                action=request.action,
                status="unavailable",
                error=str(exc),
                trace_id=request.trace_id,
            )


wikipedia_provider = WikipediaProvider()
