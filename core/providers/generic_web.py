"""
Provider recherche web (DuckDuckGo HTML, sans cle API) pour le Kernel Neron.

Type "web" (deja reserve dans ProviderType). Implemente ProviderProtocol.
Derniere etape de la cascade identite : appele seulement si memoire ET
Wikipedia n'ont rien donne.

Action supportee : "search" -- payload {"query": <texte>}.

Note : scraping HTML non-officiel (html.duckduckgo.com/html/), pas d'API
documentee -- peut casser si DuckDuckGo change sa structure de page.
Utilise `requests` (pas httpx, lecon du provider Wikipedia -- fingerprint
TLS bloque par certains sites selon la librairie).
"""

from __future__ import annotations

import asyncio
import re

import requests
from bs4 import BeautifulSoup

from .models import ProviderRequest, ProviderResponse, ProviderStatus, ProviderType

_SEARCH_URL = "https://html.duckduckgo.com/html/"
_USER_AGENT = "NeronOS/1.0 (identity-lookup provider; contact: homebox)"
_TIMEOUT = 6.0
_STOPWORDS = {"qui", "est", "le", "la", "les", "un", "une", "des", "de", "du"}


def _significant_words(text: str) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _sync_search_site(query: str, site: str) -> dict:
    """Recherche restreinte a un domaine precis (site:xxx.com) via DuckDuckGo.

    Utilisee pour trouver l'URL probable d'un profil sur un reseau social
    donne, sans jamais appeler l'API du reseau lui-meme.
    """
    headers = {"User-Agent": _USER_AGENT}
    resp = requests.post(
        _SEARCH_URL,
        data={"q": f"site:{site} {query}", "kl": "fr-fr"},
        headers=headers,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    results = soup.select("div.result")

    query_words = _significant_words(query)
    for result in results:
        title_el = result.select_one("a.result__a")
        if title_el is None:
            continue
        title = title_el.get_text(strip=True)
        url = title_el.get("href") or ""
        if site not in url:
            continue
        if not (query_words & _significant_words(title)):
            continue
        return {"found": True, "title": title, "url": url, "candidate_count": len(results)}

    return {"found": False, "title": None, "url": None, "candidate_count": len(results)}


def _sync_search(query: str) -> dict:
    headers = {"User-Agent": _USER_AGENT}
    resp = requests.post(
        _SEARCH_URL,
        data={"q": query, "kl": "fr-fr"},
        headers=headers,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    results = soup.select("div.result")

    query_words = _significant_words(query)
    for result in results:
        title_el = result.select_one("a.result__a")
        snippet_el = result.select_one("a.result__snippet") or result.select_one(
            "div.result__snippet"
        )
        if title_el is None:
            continue

        title = title_el.get_text(strip=True)
        url = title_el.get("href") or ""
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""

        combined_words = _significant_words(title) | _significant_words(snippet)
        if not (query_words & combined_words):
            continue
        if len(snippet) < 40:
            continue

        image_url = None
        try:
            page_resp = requests.get(url, headers=headers, timeout=_TIMEOUT)
            page_resp.raise_for_status()
            page_soup = BeautifulSoup(page_resp.text, "html.parser")
            og_image = page_soup.select_one('meta[property="og:image"]')
            if og_image and og_image.get("content"):
                image_url = og_image["content"]
        except requests.RequestException:
            pass

        return {
            "found": True,
            "title": title,
            "summary": snippet,
            "url": url,
            "image_url": image_url,
            "candidate_count": len(results),
        }

    return {
        "found": False,
        "title": None,
        "summary": None,
        "url": None,
        "candidate_count": len(results),
    }


class WebProvider:
    """Provider de recherche web via DuckDuckGo HTML (sans cle API)."""

    def __init__(self) -> None:
        self._status: ProviderStatus = "unknown"

    @property
    def name(self) -> str:
        return "web-search"

    @property
    def type(self) -> ProviderType:
        return "web"

    @property
    def status(self) -> ProviderStatus:
        return self._status

    @property
    def capabilities(self) -> list[str]:
        return ["identity_lookup", "search"]

    async def health(self) -> ProviderResponse:
        try:
            headers = {"User-Agent": _USER_AGENT}
            await asyncio.to_thread(
                requests.get, "https://duckduckgo.com/", timeout=_TIMEOUT, headers=headers
            )
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


web_provider = WebProvider()


async def instagram_broadcast(query: str) -> None:
    """Cherche un profil Instagram et ouvre une fenetre Dashboard si trouve.

    Taches de fond, independante de la cascade memoire->Wikipedia->web :
    ne renvoie rien, ne modifie jamais la reponse du chat.

    Import de get_gateway differe (a l'interieur de la fonction) pour
    eviter un import circulaire : core.gateway.gateway -> internal_gateway
    -> orchestrator -> core.modules.memory -> core.providers -> ce fichier.
    """
    from core.gateway.gateway import get_gateway

    try:
        result = await asyncio.to_thread(_sync_search_site, query, "instagram.com")
    except requests.RequestException as exc:
        return

    if not result.get("found"):
        return

    gw = get_gateway()
    if gw is None:
        return

    await gw.broadcast({
        "event": "memory.wikipedia_fallback",
        "data": {
            "source": "instagram",
            "query": query,
            "title": result.get("title"),
            "url": result.get("url"),
            "summary": None,
            "image_url": None,
        },
    })

    handle = result.get("url", "").rstrip("/").rsplit("/", 1)[-1]
    if handle:
        try:
            x_resp = await asyncio.to_thread(
                requests.get,
                f"https://x.com/{handle}",
                headers={"User-Agent": _USER_AGENT},
                timeout=_TIMEOUT,
            )
            title_start = x_resp.text.find("<title>")
            title_end = x_resp.text.find("</title>")
            x_title = (
                x_resp.text[title_start + 7:title_end]
                if title_start != -1 and title_end != -1
                else ""
            )
            if x_resp.status_code == 200 and "/ X" in x_title and "@" in x_title:
                await gw.broadcast({
                    "event": "memory.wikipedia_fallback",
                    "data": {
                        "source": "x",
                        "query": query,
                        "title": x_title,
                        "url": f"https://x.com/{handle}",
                        "summary": None,
                        "image_url": None,
                    },
                })
        except requests.RequestException:
            pass

    if handle:
        try:
            fb_resp = await asyncio.to_thread(
                requests.get,
                f"https://www.facebook.com/{handle}",
                headers={"User-Agent": _USER_AGENT},
                timeout=_TIMEOUT,
            )
            title_start = fb_resp.text.find("<title>")
            title_end = fb_resp.text.find("</title>")
            fb_title = (
                fb_resp.text[title_start + 7:title_end]
                if title_start != -1 and title_end != -1
                else ""
            )
            if fb_resp.status_code == 200 and fb_title and "facebook" not in fb_title.lower():
                await gw.broadcast({
                    "event": "memory.wikipedia_fallback",
                    "data": {
                        "source": "facebook",
                        "query": query,
                        "title": fb_title,
                        "url": f"https://www.facebook.com/{handle}",
                        "summary": None,
                        "image_url": None,
                    },
                })
        except requests.RequestException:
            pass

    try:
        yt_result = await asyncio.to_thread(_sync_search_site, query, "youtube.com")
    except requests.RequestException:
        yt_result = None

    if yt_result and yt_result.get("found"):
        await gw.broadcast({
            "event": "memory.wikipedia_fallback",
            "data": {
                "source": "youtube",
                "query": query,
                "title": yt_result.get("title"),
                "url": yt_result.get("url"),
                "summary": None,
                "image_url": None,
            },
        })
