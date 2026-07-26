"""
Recherche reseaux sociaux/video (Instagram, X, Facebook, YouTube) pour Neron.

Pas un ProviderProtocol classique -- ce module n'est jamais enregistre dans
provider_registry. Il expose une seule fonction, `instagram_broadcast`,
appelee en tache de fond (asyncio.create_task) depuis orchestrator.py,
independante de la reponse texte du chat.

Strategie par plateforme :
- Instagram : recherche site:instagram.com via DuckDuckGo (_sync_search_site).
- X, Facebook : acces direct par pseudo (meme pseudo qu'Instagram), pas de
  recherche site: (bloquee par ces deux plateformes -- confirme en test).
- YouTube : recherche site:youtube.com via DuckDuckGo (mieux indexe que
  X/Facebook).

Fiabilite : chaque recherche a 1 nouvelle tentative en cas d'echec (retry),
et une pause de ~1.5s separe chaque plateforme -- reduit (sans eliminer)
les echecs intermittents observes en usage reel (rate-limiting/latence
ponctuelle des plateformes scrapees sans cle API).

Import de get_gateway differe (a l'interieur de la fonction) pour eviter un
import circulaire : core.gateway.gateway -> internal_gateway -> orchestrator
-> core.modules.memory -> core.providers -> ce fichier.
"""

from __future__ import annotations

import asyncio

import requests

from .generic_web import _USER_AGENT, _TIMEOUT, _sync_search_site

_RETRY_DELAY = 1.5
_STAGGER_DELAY = 1.5


async def _search_site_with_retry(query: str, site: str) -> dict | None:
    for attempt in range(2):
        try:
            return await asyncio.to_thread(_sync_search_site, query, site)
        except requests.RequestException:
            if attempt == 0:
                await asyncio.sleep(_RETRY_DELAY)
    return None


async def _fetch_profile_with_retry(url: str) -> requests.Response | None:
    for attempt in range(2):
        try:
            return await asyncio.to_thread(
                requests.get, url, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT
            )
        except requests.RequestException:
            if attempt == 0:
                await asyncio.sleep(_RETRY_DELAY)
    return None


def _extract_title(html: str) -> str:
    start = html.find("<title>")
    end = html.find("</title>")
    return html[start + 7:end] if start != -1 and end != -1 else ""


async def instagram_broadcast(query: str) -> None:
    """Cherche un profil Instagram/X/Facebook/YouTube et ouvre une fenetre
    Dashboard pour chaque plateforme ou un resultat est trouve.

    Tache de fond, independante de la cascade memoire->Wikipedia->web :
    ne renvoie rien, ne modifie jamais la reponse du chat.
    """
    from core.gateway.gateway import get_gateway

    result = await _search_site_with_retry(query, "instagram.com")
    if not result or not result.get("found"):
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
        await asyncio.sleep(_STAGGER_DELAY)
        x_resp = await _fetch_profile_with_retry(f"https://x.com/{handle}")
        if x_resp is not None:
            x_title = _extract_title(x_resp.text)
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

    if handle:
        await asyncio.sleep(_STAGGER_DELAY)
        fb_resp = await _fetch_profile_with_retry(f"https://www.facebook.com/{handle}")
        if fb_resp is not None:
            fb_title = _extract_title(fb_resp.text)
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

    await asyncio.sleep(_STAGGER_DELAY)
    yt_result = await _search_site_with_retry(query, "youtube.com")
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
