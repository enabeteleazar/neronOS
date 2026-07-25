"""
Provider Wikipedia pour le Kernel Neron.

Type "generic" (le type "knowledge" etant deja pris par ObsidianKnowledgeProvider).
Implemente ProviderProtocol pour s'enregistrer dans provider_registry.

Action supportee : "search" -- payload {"query": <nom ou sujet>}.

Note technique : utilise `requests` (synchrone, execute via asyncio.to_thread)
plutot que `httpx`. Wikipedia bloque les requetes httpx/httpcore avec un 403
"robot policy" independamment du User-Agent (fingerprint TLS bas niveau),
confirme par test isole -- requests passe sans probleme avec les memes
en-tetes et URL.
"""

from __future__ import annotations

import asyncio

import requests
import re

from .models import ProviderRequest, ProviderResponse, ProviderStatus, ProviderType

_SEARCH_URL = "https://fr.wikipedia.org/w/api.php"
_SUMMARY_URL = "https://fr.wikipedia.org/api/rest_v1/page/summary/{title}"
_USER_AGENT = "NeronOS/1.0 (identity-lookup provider; contact: homebox)"
_TIMEOUT = 5.0


def _sync_search(query: str) -> dict:
    headers = {"User-Agent": _USER_AGENT}
    search_resp = requests.get(
        _SEARCH_URL,
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": 5,
            "format": "json",
        },
        headers=headers,
        timeout=_TIMEOUT,
    )
    search_resp.raise_for_status()
    search_hits = search_resp.json().get("query", {}).get("search", [])

    if not search_hits:
        return {
            "found": False,
            "title": None,
            "summary": None,
            "url": None,
            "candidate_count": 0,
        }

    def _significant_words(text: str) -> set[str]:
        stopwords = {"qui", "est", "le", "la", "les", "un", "une", "des", "de", "du"}
        words = re.findall(r"\w+", text.lower())
        return {w for w in words if len(w) > 2 and w not in stopwords}

    query_words = _significant_words(query)
    top_hit = None
    for hit in search_hits:
        title_words = _significant_words(hit["title"])
        if query_words & title_words:
            top_hit = hit
            break

    if top_hit is None:
        return {
            "found": False,
            "title": None,
            "summary": None,
            "url": None,
            "candidate_count": len(search_hits),
        }

    top_title = top_hit["title"]
    summary_resp = requests.get(
        _SUMMARY_URL.format(title=top_title.replace(" ", "_")),
        headers=headers,
        timeout=_TIMEOUT,
    )
    summary_resp.raise_for_status()
    summary_data = summary_resp.json()

    return {
        "found": True,
        "title": summary_data.get("title", top_title),
        "summary": summary_data.get("extract"),
        "url": summary_data.get("content_urls", {}).get("desktop", {}).get("page"),
        "candidate_count": len(search_hits),
    }


def _sync_health() -> None:
    headers = {"User-Agent": _USER_AGENT}
    resp = requests.get(
        _SEARCH_URL,
        params={"action": "query", "meta": "siteinfo", "format": "json"},
        headers=headers,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()


class WikipediaProvider:
    """Provider de recherche d'identite via l'API Wikipedia (fr), sur `requests`."""

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
            await asyncio.to_thread(_sync_health)
            self._status = "healthy"
            return ProviderResponse(
                provider=self.name, action="health", status="healthy", result={"ok": True}
            )
        except requests.RequestException as exc:
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
            result = await asyncio.to_thread(_sync_search, query)
            self._status = "healthy"
            return ProviderResponse(
                provider=self.name,
                action=request.action,
                status="healthy",
                result=result,
                trace_id=request.trace_id,
            )
        except requests.RequestException as exc:
            self._status = "degraded"
            return ProviderResponse(
                provider=self.name,
                action=request.action,
                status="unavailable",
                error=str(exc),
                trace_id=request.trace_id,
            )


wikipedia_provider = WikipediaProvider()
