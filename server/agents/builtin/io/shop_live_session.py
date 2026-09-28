"""core/agents/io/shop_live_session.py
Neron Core — Sessions navigateur interactives (neronShop)  v0.1.0

Brique bas niveau pour l'intégration "connexion en direct dans le Dashboard" :
une LiveSession pilote un navigateur Chromium Playwright et diffuse son écran
image par image via le protocole CDP (Page.startScreencast), tout en relayant
en retour les événements souris/clavier envoyés par le client. L'humain tape
son mot de passe et son 2FA DIRECTEMENT dans ce navigateur — jamais transmis
au serveur sous une autre forme — puis l'automatisation continue sur cette
même session (mêmes cookies, même page).

Ne dépend d'aucune infrastructure système supplémentaire (pas de Xvfb/VNC) :
le screencast CDP fonctionne aussi en headless, Chromium composite les frames
même sans affichage réel.

Pas de couche FastAPI ici volontairement — voir core/api/shop_live_routes.py
pour l'exposition WebSocket. Ce module est testable seul, sans serveur HTTP.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from core.config import settings
from core.config.paths import NERON_DATA_DIR

logger = logging.getLogger("agent.shop.live")

try:
    from playwright.async_api import async_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

_HEADLESS          = bool(getattr(settings, "SHOP_HEADLESS", True))
_USER_DATA_DIR     = str(getattr(settings, "SHOP_USER_DATA_DIR", NERON_DATA_DIR / "shop_browser_profile"))
_STORAGE_STATE_PATH = str(getattr(settings, "SHOP_STORAGE_STATE_PATH", NERON_DATA_DIR / "shop_amazon_state.json"))
_SESSION_TTL_S     = 600.0  # une session de login jamais terminée par l'humain ne doit pas tourner indéfiniment

FrameHandler = Callable[[bytes], Awaitable[None]]


class LiveSessionError(Exception):
    """Erreur de cycle de vie d'une LiveSession (démarrage, dispatch, etc.)."""


class LiveSession:
    """Une session Chromium pilotable à distance (écran diffusé + input relayé)."""

    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.created_at = time.monotonic()
        self._playwright = None
        self._context = None
        self.page = None
        self._cdp = None
        self._frame_handlers: list[FrameHandler] = []
        self._closed = False

    async def start(self, start_url: str) -> None:
        if not _PLAYWRIGHT_AVAILABLE:
            raise LiveSessionError("Playwright n'est pas installé sur ce serveur.")
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=_USER_DATA_DIR,
            headless=_HEADLESS,
            locale="fr-FR",
            timezone_id="Europe/Paris",
            viewport={"width": 1280, "height": 800},
        )
        self.page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        await self.page.goto(start_url, wait_until="domcontentloaded")
        self._cdp = await self._context.new_cdp_session(self.page)
        self._cdp.on("Page.screencastFrame", self._on_screencast_frame)
        logger.info("LiveSession %s démarrée sur %s", self.id, start_url)

    def add_frame_handler(self, handler: FrameHandler) -> None:
        self._frame_handlers.append(handler)

    def remove_frame_handler(self, handler: FrameHandler) -> None:
        if handler in self._frame_handlers:
            self._frame_handlers.remove(handler)

    def _on_screencast_frame(self, params: dict[str, Any]) -> None:
        # Callback CDP synchrone -- on planifie le traitement (async) sans bloquer.
        asyncio.create_task(self._handle_frame(params))

    async def _handle_frame(self, params: dict[str, Any]) -> None:
        try:
            data = base64.b64decode(params["data"])
            for handler in list(self._frame_handlers):
                await handler(data)
        except Exception as e:
            logger.warning("LiveSession %s: erreur traitement frame : %s", self.id, e)
        finally:
            # Chrome met le screencast en pause tant que la frame n'est pas
            # acquittée -- sans ça, une seule frame arrive puis plus rien.
            try:
                await self._cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
            except Exception:
                pass

    async def start_screencast(self, *, quality: int = 70, max_width: int = 1280, max_height: int = 800) -> None:
        await self._cdp.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": quality,
            "maxWidth": max_width,
            "maxHeight": max_height,
            "everyNthFrame": 1,
        })
        logger.info("LiveSession %s: screencast démarré", self.id)

    async def stop_screencast(self) -> None:
        try:
            await self._cdp.send("Page.stopScreencast")
        except Exception:
            pass

    async def dispatch_input(self, event: dict[str, Any]) -> None:
        """Traduit un événement JSON reçu du client (souris/clavier) en action
        Playwright réelle sur la page. Contrat MVP :
          {"type": "mousemove"|"mousedown"|"mouseup"|"click", "x":.., "y":.., "button": "left"}
          {"type": "wheel", "deltaX":.., "deltaY":..}
          {"type": "keydown"|"keyup", "key": "a"}   (noms de touches Playwright)
          {"type": "type", "text": "..."}
        """
        kind = event.get("type")
        try:
            if kind == "mousemove":
                await self.page.mouse.move(event["x"], event["y"])
            elif kind == "mousedown":
                await self.page.mouse.move(event["x"], event["y"])
                await self.page.mouse.down(button=event.get("button", "left"))
            elif kind == "mouseup":
                await self.page.mouse.up(button=event.get("button", "left"))
            elif kind == "click":
                await self.page.mouse.click(event["x"], event["y"], button=event.get("button", "left"))
            elif kind == "wheel":
                await self.page.mouse.wheel(event.get("deltaX", 0), event.get("deltaY", 0))
            elif kind == "keydown":
                await self.page.keyboard.down(event["key"])
            elif kind == "keyup":
                await self.page.keyboard.up(event["key"])
            elif kind == "type":
                await self.page.keyboard.type(event["text"])
            else:
                logger.warning("LiveSession %s: événement input inconnu ignoré (%s)", self.id, kind)
        except Exception as e:
            logger.warning("LiveSession %s: échec dispatch input (%s) : %s", self.id, kind, e)

    async def export_storage_state(self, path: str | None = None) -> str:
        """Persiste les cookies de la session courante -- appelé une fois
        l'humain connecté, pour que les prochaines exécutions headless de
        neronShop réutilisent cette authentification sans repasser par une
        session live."""
        target = path or _STORAGE_STATE_PATH
        await self._context.storage_state(path=target)
        logger.info("LiveSession %s: session exportée vers %s", self.id, target)
        return target

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.stop_screencast()
        try:
            if self._context:
                await self._context.close()
        finally:
            if self._playwright:
                await self._playwright.stop()
        logger.info("LiveSession %s fermée", self.id)


class LiveSessionManager:
    """Registre process-local des sessions live en cours."""

    def __init__(self) -> None:
        self._sessions: dict[str, LiveSession] = {}
        self._purge_task: Optional[asyncio.Task] = None

    def _ensure_purge_loop(self) -> None:
        # Démarrée paresseusement à la première session -- pas de tâche de
        # fond qui tourne pour rien si neronShop n'est jamais utilisé en mode
        # live.
        if self._purge_task is None or self._purge_task.done():
            self._purge_task = asyncio.create_task(self._purge_loop())

    async def _purge_loop(self) -> None:
        while True:
            await asyncio.sleep(60.0)
            if not self._sessions:
                return  # rien à surveiller -- repartira paresseusement au prochain create()
            await self.purge_expired()

    async def create(self, start_url: str) -> LiveSession:
        self._ensure_purge_loop()
        session = LiveSession(str(uuid.uuid4()))
        await session.start(start_url)
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Optional[LiveSession]:
        return self._sessions.get(session_id)

    async def close(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await session.close()

    async def purge_expired(self) -> None:
        """Ferme les sessions de login jamais terminées par l'humain (TTL) --
        évite qu'un onglet oublié laisse un Chromium tourner indéfiniment."""
        now = time.monotonic()
        expired = [sid for sid, s in self._sessions.items() if now - s.created_at > _SESSION_TTL_S]
        for sid in expired:
            logger.warning("LiveSession %s expirée (TTL) -- fermeture forcée.", sid)
            await self.close(sid)


_manager: Optional[LiveSessionManager] = None


def get_live_session_manager() -> LiveSessionManager:
    global _manager
    if _manager is None:
        _manager = LiveSessionManager()
    return _manager
