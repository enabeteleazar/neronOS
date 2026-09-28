"""core/api/shop_live_routes.py
Neron Core — API live view neronShop  v0.1.0

Expose les sessions de navigation interactives définies dans
agents.builtin.io.shop_live_session : création, diffusion d'écran (CDP
screencast) + relais d'input via WebSocket, et clôture (export de session).
Sert de brique backend au futur composant Dashboard "connexion en direct" :
l'humain se connecte lui-même dans le navigateur diffusé (mot de passe et
2FA jamais transmis au serveur autrement que par ses propres clics/frappes),
puis neronShop réutilise cette même session, cookies compris.

Authentification :
  - Endpoints REST (POST) : Bearer token classique (verify_api_key), comme
    le reste de l'API Core.
  - WebSocket : Depends(Request) ne fonctionne pas sur une poignée de main
    WS, donc on lit nous-mêmes l'en-tête Authorization de la requête HTTP
    d'upgrade (WebSocket.headers l'expose, comme sur une requête normale).
    Le navigateur ne le pose PAS lui-même -- system/deploy/caddy/Caddyfile
    l'injecte côté serveur sur tout /api/* (y compris les upgrades
    WebSocket), exactement comme pour les routes REST. Le Dashboard n'a
    donc jamais accès à la clé, ce qui suppose que ce router est monté
    derrière /api/* (jamais exposé directement sur un autre chemin).
"""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from core.api.auth import verify_api_key
from core.config import settings
from core.infrastructure.auth import AUTHORIZATION_HEADER, BEARER_PREFIX

logger = logging.getLogger("core.api.shop_live")

router = APIRouter(prefix="/shop/live", tags=["shop_live"])


class CreateSessionRequest(BaseModel):
    start_url: str = "https://www.amazon.fr"


class SessionInfo(BaseModel):
    session_id: str


class CompleteSessionResponse(BaseModel):
    status: str
    storage_state_path: str


def _get_manager():
    from agents.builtin.io.shop_live_session import get_live_session_manager
    return get_live_session_manager()


def _check_ws_auth(websocket: WebSocket) -> bool:
    configured = str(settings.API_KEY or "").strip()
    if not configured or configured == "changez_moi":
        return False
    authorization = websocket.headers.get(AUTHORIZATION_HEADER)
    if not authorization or not authorization.startswith(BEARER_PREFIX):
        return False
    supplied = authorization.split(" ", 1)[1].strip()
    return bool(supplied) and hmac.compare_digest(supplied, configured)


@router.post("/sessions", response_model=SessionInfo, dependencies=[Depends(verify_api_key)])
async def create_session(body: CreateSessionRequest) -> SessionInfo:
    """Démarre une LiveSession et navigue vers start_url (Amazon.fr par défaut)."""
    manager = _get_manager()
    try:
        session = await manager.create(body.start_url)
    except Exception as e:
        logger.error("Échec création LiveSession : %s", e)
        raise HTTPException(status_code=500, detail="Impossible de démarrer la session navigateur.")
    return SessionInfo(session_id=session.id)


@router.post(
    "/sessions/{session_id}/complete",
    response_model=CompleteSessionResponse,
    dependencies=[Depends(verify_api_key)],
)
async def complete_session(session_id: str) -> CompleteSessionResponse:
    """Marque la connexion humaine terminée : exporte les cookies de session
    puis ferme la LiveSession. neronShop réutilisera ce fichier au prochain
    lancement headless (cf. shop_agent._seed_authenticated_session)."""
    manager = _get_manager()
    session = manager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session introuvable ou déjà fermée.")
    path = await session.export_storage_state()
    await manager.close(session_id)
    return CompleteSessionResponse(status="ok", storage_state_path=path)


@router.websocket("/sessions/{session_id}/stream")
async def stream_session(websocket: WebSocket, session_id: str) -> None:
    """Diffuse l'écran (frames JPEG binaires) et reçoit en retour des
    événements input JSON -- cf. LiveSession.dispatch_input pour le contrat."""
    if not _check_ws_auth(websocket):
        await websocket.close(code=4401)
        return

    manager = _get_manager()
    session = manager.get(session_id)
    if session is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    logger.info("Client connecté au flux live de la session %s", session_id)

    async def on_frame(data: bytes) -> None:
        try:
            await websocket.send_bytes(data)
        except Exception:
            pass

    session.add_frame_handler(on_frame)
    try:
        await session.start_screencast()
        while True:
            message = await websocket.receive_json()
            await session.dispatch_input(message)
    except WebSocketDisconnect as e:
        logger.info("Client déconnecté du flux live de la session %s (code=%s, reason=%r)", session_id, e.code, e.reason)
    except Exception:
        logger.exception("Erreur inattendue sur le flux live de la session %s", session_id)
    finally:
        session.remove_frame_handler(on_frame)
        await session.stop_screencast()
