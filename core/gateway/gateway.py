# neron/gateway.py
# Gateway WebSocket — Plan de contrôle central inspiré d'OpenClaw.
# Port par défaut : ws://0.0.0.0:18789
# Interface avec l'extérieur (API, webhooks, etc.)

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Coroutine

import websockets
from websockets.exceptions import ConnectionClosed
from websockets.asyncio.server import ServerConnection

from core.identity import build_identity_prompt

if TYPE_CHECKING:
    from core.pipeline.routing.agent_router import AgentRouter
    from modules.sessions import SessionStore
    from modules.skills import SkillRegistry
    from agents.builtin.io.stt_agent import STTAgent
    from agents.builtin.io.tts_agent import TTSAgent

# Taille max d'un audio décodé (base64 -> bytes), avant délégation à STTAgent
# (qui applique lui-même AUDIO_MAX_MB — cette limite protège juste le decode).
MAX_VOICE_AUDIO_BYTES = 15 * 1024 * 1024  # 15 MB

print(">>> GATEWAY.PY CHARGÉ DEPUIS CE FICHIER <<<", flush=True)
logger = logging.getLogger("neron.gateway")

# ──────────────────────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 18789
MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10 MB

# Codes d'erreur JSON-RPC 2.0
ERROR_PARSE_ERROR      = -32700
ERROR_INVALID_REQUEST  = -32600
ERROR_METHOD_NOT_FOUND = -32601
ERROR_INVALID_PARAMS   = -32602
ERROR_INTERNAL_ERROR   = -32603
ERROR_AUTH_REQUIRED    = 401

# ──────────────────────────────────────────────────────────────────────────────
# Dataclasses internes
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class GatewayConfig:
    """Configuration du serveur Gateway."""

    host:            str        = DEFAULT_HOST
    port:            int        = DEFAULT_PORT
    token:           str | None = None
    max_connections: int        = 64
    ping_interval:   float      = 20.0
    ping_timeout:    float      = 10.0


@dataclass
class ConnectedClient:
    """Représente un client connecté au gateway."""

    ws:            ServerConnection
    client_id:     str  = field(default_factory=lambda: str(uuid.uuid4())[:8])
    authenticated: bool = False

    def __hash__(self) -> int:
        return hash(self.client_id)


# ──────────────────────────────────────────────────────────────────────────────
# Types pour les handlers
# ──────────────────────────────────────────────────────────────────────────────

HandlerType = Callable[
    ["ConnectedClient", dict[str, Any]],
    Coroutine[Any, Any, dict[str, Any] | None],
]


# ──────────────────────────────────────────────────────────────────────────────
# Gateway principale
# ──────────────────────────────────────────────────────────────────────────────


class NeronGateway:
    """
    Serveur WebSocket mono-port, multi-clients.

    Dispatch les méthodes JSON-RPC vers AgentRouter / SessionStore /
    SkillRegistry. Gère l'authentification optionnelle par token et le
    streaming des réponses d'agents.

    Attributes:
        config:   Configuration du gateway.
        sessions: Magasin de sessions actif.
        skills:   Registre des skills disponibles.
        agent:    Routeur d'agents LLM.
    """

    def __init__(
        self,
        config:           GatewayConfig  | None = None,
        agent_router:     "AgentRouter"  | None = None,
        session_store:    "SessionStore" | None = None,
        skill_registry:   "SkillRegistry"| None = None,
        stt_agent:        "STTAgent"     | None = None,
        tts_agent:        "TTSAgent"     | None = None,
    ) -> None:
        self.config    = config or GatewayConfig()
        self.sessions  = session_store  or SessionStore()
        self.skills    = skill_registry or SkillRegistry()
        self.agent     = agent_router   or AgentRouter(
            sessions=self.sessions,
            skills=self.skills,
        )
        # Injectés depuis app.py (globals stt_agent/tts_agent déjà chargés
        # au démarrage) — peuvent rester None si STT/TTS désactivés.
        self.stt_agent = stt_agent
        self.tts_agent = tts_agent
        self._clients:  dict[str, ConnectedClient] = {}
        self._handlers: dict[str, HandlerType]     = {
            "ping":              self._ping,
            "chat.send":         self._chat_send,
            "agent.run":         self._agent_run,
            "session.new":       self._session_new,
            "session.list":      self._session_list,
            "session.get":       self._session_get,
            "skill.call":        self._skill_call,
            "skill.list":        self._skill_list,
            "voice.transcribe":  self._voice_transcribe,
            "voice.send":        self._voice_send,
        }

    # ── Entrée serveur ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Démarre le serveur WebSocket et bloque indéfiniment."""
        cfg = self.config
        logger.info("Neron Gateway démarrage sur ws://%s:%d", cfg.host, cfg.port)
        try:
            async with websockets.serve(
                self._handle_client,
                cfg.host,
                cfg.port,
                ping_interval=cfg.ping_interval,
                ping_timeout=cfg.ping_timeout,
                max_size=MAX_MESSAGE_SIZE,
            ):
                logger.info("Gateway en écoute ✓")
                await asyncio.Future()  # tourne indéfiniment
        except OSError as e:
            if getattr(e, 'errno', None) == 98:
                logger.warning("Port %d déjà utilisé, gateway non démarré", cfg.port)
                return
            raise

    # ── Connexion client ────────────────────────────────────────────────────

    async def _handle_client(self, ws: ServerConnection) -> None:
        """
        Gère le cycle de vie complet d'un client WebSocket.

        Vérifie la limite de connexions, crée une entrée client, gère
        l'authentification initiale, puis dispatch chaque message reçu
        jusqu'à la déconnexion.

        Args:
            ws: Protocole WebSocket du client entrant.
        """
        # FIX: max_connections déclaré dans GatewayConfig mais jamais appliqué
        if len(self._clients) >= self.config.max_connections:
            logger.warning("Limite de connexions atteinte (%d), client refusé", self.config.max_connections)
            await ws.close(1013, "Trop de connexions")
            return

        client = ConnectedClient(ws=ws)
        self._clients[client.client_id] = client
        logger.info("[%s] connexion depuis %s", client.client_id, ws.remote_address)

        if self.config.token is None:
            client.authenticated = True
        else:
            await self._send(
                ws, _event("gateway.auth_required", {"message": "Token requis"})
            )

        try:
            async for raw in ws:
                await self._dispatch(client, raw)
        except ConnectionClosed:
            pass
        except Exception as e:
            logger.warning("[%s] connexion fermée : %s", client.client_id, e)
        finally:
            self._clients.pop(client.client_id, None)
            logger.info("[%s] déconnexion", client.client_id)

    # ── Dispatch JSON-RPC ───────────────────────────────────────────────────

    async def _dispatch(self, client: ConnectedClient, raw: str | bytes) -> None:
        """
        Parse et dispatch un message JSON-RPC 2.0.

        Args:
            client: Client émetteur du message.
            raw:    Payload brut (JSON).
        """
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.debug("[%s] JSON decode error: %s", client.client_id, e)
            await self._send(client.ws, _error(None, ERROR_PARSE_ERROR, "Parse error"))
            return


        if not isinstance(frame, dict):
            await self._send(
                client.ws,
                _error(None, ERROR_INVALID_REQUEST, "Request must be an object"),
            )
            return

        req_id = frame.get("id")
        method = frame.get("method", "")

        if not isinstance(method, str) or not method:
            await self._send(
                client.ws,
                _error(req_id, ERROR_INVALID_REQUEST, "Invalid method"),
            )
            return

        params = frame.get("params", {})
        if not isinstance(params, dict):
            await self._send(
                client.ws,
                _error(req_id, ERROR_INVALID_PARAMS, "Params must be an object"),
            )
            return

        await self._handle_method(client, req_id, method, params)

    async def _handle_method(
        self,
        client: ConnectedClient,
        req_id: Any,
        method: str,
        params: dict[str, Any],
    ) -> None:
        """
        Gère l'authentification et dispatch vers le handler approprié.

        Args:
            client: Client émetteur.
            req_id: ID de la requête JSON-RPC.
            method: Nom de la méthode.
            params: Paramètres de l'appel.
        """
        if method == "gateway.auth":
            await self._authenticate(client, req_id, params)
            return

        if not client.authenticated:
            await self._send(
                client.ws,
                _error(req_id, ERROR_AUTH_REQUIRED, "Non authentifié"),
            )
            return

        handler = self._handlers.get(method)
        if handler is None:
            await self._send(
                client.ws,
                _error(req_id, ERROR_METHOD_NOT_FOUND, f"Méthode inconnue : {method}"),
            )
            return

        try:
            result = await handler(client, params)
            if result is not None:
                await self._send(client.ws, _result(req_id, result))
        except ValueError as e:
            logger.warning("[%s] erreur métier %s: %s", client.client_id, method, e)
            await self._send(client.ws, _error(req_id, ERROR_INVALID_PARAMS, str(e)))
        except Exception as e:
            logger.exception("[%s] erreur handler %s", client.client_id, method)
            await self._send(client.ws, _error(req_id, ERROR_INTERNAL_ERROR, str(e)))

    # ── Handlers ────────────────────────────────────────────────────────────

    async def _ping(self, client: ConnectedClient, params: dict) -> dict:
        """Répond au ping du client."""
        del client, params  # non utilisés
        return {"pong": True}

    async def _authenticate(
        self, client: ConnectedClient, req_id: Any, params: dict
    ) -> None:
        """
        Authentifie le client avec un token.

        Args:
            client: Client à authentifier.
            req_id: ID de la requête.
            params: Doit contenir 'token'.
        """
        token = params.get("token", "")
        if self.config.token and token == self.config.token:
            client.authenticated = True
            await self._send(client.ws, _result(req_id, {"ok": True}))
        else:
            await self._send(
                client.ws,
                _error(req_id, ERROR_AUTH_REQUIRED, "Token invalide"),
            )

    async def _session_new(self, client: ConnectedClient, params: dict) -> dict:
        """
        Crée une nouvelle session.

        Args:
            client: Client demandeur.
            params: Contient 'session_id' (optionnel) et 'system'.

        Returns:
            ID de la session créée.
        """
        del client  # non utilisé
        session_id = params.get("session_id") or str(uuid.uuid4())
        system     = params.get("system") or build_identity_prompt()
        session    = self.sessions.create(session_id, system_prompt=system)
        return {"session_id": session.id, "created": True}

    async def _session_list(self, client: ConnectedClient, params: dict) -> dict:
        """
        Liste toutes les sessions actives.

        Args:
            client: Client demandeur.
            params: Non utilisé.

        Returns:
            Liste des sessions avec leur ID et nombre de tours.
        """
        # FIX: del client, params — client était absent du del, inconsistant avec les autres handlers
        del client, params
        sessions = self.sessions.list_all()
        return {
            "sessions": [
                {"id": s.id, "turns": len(s.history)} for s in sessions
            ]
        }

    async def _session_get(self, client: ConnectedClient, params: dict) -> dict:
        """
        Récupère les détails d'une session.

        Args:
            client: Client demandeur.
            params: Doit contenir 'session_id'.

        Returns:
            Historique et prompt système de la session.

        Raises:
            ValueError: Si la session n'existe pas.
        """
        del client  # non utilisé
        session_id = params.get("session_id")
        if not session_id:
            raise ValueError("session_id requis")

        session = self.sessions.get(session_id)
        if session is None:
            raise ValueError(f"Session inconnue : {session_id}")

        return {
            "session_id": session.id,
            "history":    session.history,
            "system":     session.system_prompt,
        }

    async def _chat_send(self, client: ConnectedClient, params: dict) -> None:
        """
        Envoie un message en streaming.

        Envoie des events 'agent.token' par petits blocs, suivi d'un event
        'agent.done' avec les statistiques d'usage.

        Args:
            client: Client destinataire des events.
            params: Contient 'session_id' et 'message'.
        """
        # FIX: caractère chinois parasite "小块" retiré de la docstring
        session_id = params.get("session_id", "default")
        message    = params.get("message", "")

        if not message:
            await self._send(
                client.ws,
                _event("agent.error", {"message": "Message vide"}),
            )
            return

        await self._run_text_and_emit(client, session_id, message)

    async def _run_text_and_emit(
        self,
        client: ConnectedClient,
        session_id: str,
        message: str,
        extra_usage: dict | None = None,
    ) -> "object | None":
        """
        Fait passer un texte par l'orchestrateur et émet 'agent.token' /
        'agent.done' — logique partagée entre chat.send et voice.send.

        Args:
            client: Client destinataire des events.
            session_id: Session concernée.
            message: Texte à traiter (déjà transcrit, le cas échéant).
            extra_usage: Champs additionnels à fusionner dans 'usage'
                (ex : infos de transcription pour voice.send).

        Returns:
            Le CoreResult de l'orchestrateur si succès, sinon None.
        """
        try:
            from core.pipeline.orchestrator import get_core_orchestrator
            result = await get_core_orchestrator().handle(
                message,
                session_id=session_id,
                source_channel="websocket",
                user_id=client.client_id,
            )
            await self._send(
                client.ws,
                _event(
                    "agent.token",
                    {
                        "session_id": session_id,
                        "token": result.response,
                    },
                ),
            )
            usage = {
                "intent": result.intent,
                "selected_route": result.decision.selected_route,
                "execution_time_ms": result.elapsed_ms,
            }
            if extra_usage:
                usage.update(extra_usage)
            await self._send(
                client.ws,
                _event("agent.done", {
                    "session_id": session_id,
                    "usage": usage,
                }),
            )
            return result
        except Exception as e:
            logger.exception("[%s] erreur run_text_and_emit", client.client_id)
            await self._send(
                client.ws,
                _event("agent.error", {
                    "session_id": session_id,
                    "message":    str(e),
                }),
            )
            return None

    async def _agent_run(self, client: ConnectedClient, params: dict) -> None:
        """
        Exécute un agent avec tool-use et streaming.

        Streame les tokens et les events de tool calls.

        Args:
            client: Client destinataire des events.
            params: Contient 'session_id', 'message', 'thinking'.
        """
        session_id = params.get("session_id", "default")
        message    = params.get("message", "")
        thinking   = params.get("thinking", False)

        try:
            async for event in self.agent.run_stream(
                session_id, message, thinking=thinking
            ):
                await self._send(client.ws, event)
        except Exception as e:
            logger.exception("[%s] erreur agent_run", client.client_id)
            await self._send(
                client.ws,
                _event("agent.error", {
                    "session_id": session_id,
                    "message":    str(e),
                }),
            )

    def _decode_voice_audio(self, params: dict) -> tuple[bytes, str]:
        """
        Décode et valide l'audio base64 reçu en params.

        Args:
            params: Doit contenir 'audio_b64'. 'filename' optionnel
                (défaut 'audio.wav') — son extension détermine le format
                attendu par STTAgent (.wav/.mp3/.m4a/.ogg/.flac/.webm).

        Returns:
            (audio_bytes, filename)

        Raises:
            ValueError: audio_b64 manquant, invalide, ou trop volumineux.
        """
        audio_b64 = params.get("audio_b64")
        if not audio_b64:
            raise ValueError("audio_b64 requis")

        filename = params.get("filename") or "audio.wav"

        try:
            audio_bytes = base64.b64decode(audio_b64, validate=True)
        except (binascii.Error, ValueError) as e:
            raise ValueError(f"audio_b64 invalide : {e}") from e

        if not audio_bytes:
            raise ValueError("audio décodé vide")

        if len(audio_bytes) > MAX_VOICE_AUDIO_BYTES:
            raise ValueError(
                f"audio trop volumineux : {len(audio_bytes)} > "
                f"{MAX_VOICE_AUDIO_BYTES} bytes"
            )

        return audio_bytes, filename

    async def _voice_transcribe(self, client: ConnectedClient, params: dict) -> dict:
        """
        Transcrit un audio en texte, sans passer par l'orchestrateur.

        Args:
            client: Client demandeur.
            params: 'audio_b64' (requis), 'filename' (optionnel).

        Returns:
            Transcription et métadonnées STT.

        Raises:
            ValueError: STT indisponible, audio invalide, ou échec transcription.
        """
        del client  # non utilisé
        if self.stt_agent is None:
            raise ValueError("STT non disponible (désactivé dans cette configuration)")

        audio_bytes, filename = self._decode_voice_audio(params)
        result = await self.stt_agent.transcribe(audio_bytes, filename)
        if not result.success:
            raise ValueError(f"STT indisponible : {result.error}")

        return {
            "text":           result.content,
            "language":       result.metadata.get("language"),
            "stt_latency_ms": result.latency_ms,
        }

    async def _voice_send(self, client: ConnectedClient, params: dict) -> None:
        """
        Transcrit un audio puis exécute le pipeline complet (équivalent
        vocal de chat.send) — émet 'voice.transcription', puis
        'agent.token'/'agent.done', et optionnellement 'voice.audio'
        (réponse synthétisée en TTS) si 'synthesize' est vrai.

        Args:
            client: Client destinataire des events.
            params: 'audio_b64' (requis), 'filename' (optionnel),
                'session_id' (optionnel), 'synthesize' (bool, défaut False).
        """
        session_id = params.get("session_id", "default")

        if self.stt_agent is None:
            await self._send(
                client.ws,
                _event("agent.error", {
                    "session_id": session_id,
                    "message": "STT non disponible (désactivé dans cette configuration)",
                }),
            )
            return

        try:
            audio_bytes, filename = self._decode_voice_audio(params)
        except ValueError as e:
            await self._send(
                client.ws,
                _event("agent.error", {"session_id": session_id, "message": str(e)}),
            )
            return

        stt_result = await self.stt_agent.transcribe(audio_bytes, filename)
        if not stt_result.success:
            await self._send(
                client.ws,
                _event("agent.error", {
                    "session_id": session_id,
                    "message": f"STT indisponible : {stt_result.error}",
                }),
            )
            return

        transcription = stt_result.content
        if not transcription:
            await self._send(
                client.ws,
                _event("agent.error", {
                    "session_id": session_id,
                    "message": "Transcription vide",
                }),
            )
            return

        await self._send(
            client.ws,
            _event("voice.transcription", {
                "session_id":     session_id,
                "text":           transcription,
                "language":       stt_result.metadata.get("language"),
                "stt_latency_ms": stt_result.latency_ms,
            }),
        )

        result = await self._run_text_and_emit(
            client,
            session_id,
            transcription,
            extra_usage={
                "transcription":  transcription,
                "stt_latency_ms": stt_result.latency_ms,
            },
        )

        synthesize = bool(params.get("synthesize", False))
        if not synthesize or result is None:
            return

        if self.tts_agent is None:
            await self._send(
                client.ws,
                _event("voice.error", {
                    "session_id": session_id,
                    "message": "TTS non disponible (désactivé dans cette configuration)",
                }),
            )
            return

        tts_result = await self.tts_agent.synthesize(result.response)
        if not tts_result.success:
            await self._send(
                client.ws,
                _event("voice.error", {
                    "session_id": session_id,
                    "message": f"TTS indisponible : {tts_result.error}",
                }),
            )
            return

        await self._send(
            client.ws,
            _event("voice.audio", {
                "session_id":     session_id,
                "audio_b64":      base64.b64encode(
                    tts_result.metadata["audio_bytes"]
                ).decode("ascii"),
                "mimetype":       tts_result.metadata.get("mimetype", "audio/wav"),
                "tts_latency_ms": tts_result.latency_ms,
            }),
        )

    async def _skill_list(self, client: ConnectedClient, params: dict) -> dict:
        """
        Liste tous les skills disponibles.

        Args:
            client: Client demandeur.
            params: Non utilisé.

        Returns:
            Liste des skills avec nom et description.
        """
        del client, params
        skills = self.skills.list_all()
        return {
            "skills": [
                {"name": s.name, "description": s.description} for s in skills
            ]
        }

    async def _skill_call(self, client: ConnectedClient, params: dict) -> dict:
        """
        Appelle un skill par son nom.

        Args:
            client: Client demandeur.
            params: Doit contenir 'name' et 'params'.

        Returns:
            Résultat de l'exécution du skill.
        """
        del client  # non utilisé
        name = params.get("name")
        if not name:
            raise ValueError("name requis")

        skill_params = params.get("params", {})
        result       = await self.skills.call(name, **skill_params)
        return {"result": result}

    # ── Helpers envoi ───────────────────────────────────────────────────────

    async def _send(self, ws: ServerConnection, payload: dict) -> None:
        """
        Sérialise et envoie un payload JSON au client.

        Attrape silencieusement les erreurs de connexion fermée.

        Args:
            ws:      Socket du client.
            payload: Objet à sérialiser en JSON.
        """
        try:
            await ws.send(json.dumps(payload, ensure_ascii=False))
        except ConnectionClosed:
            pass

    async def broadcast(self, payload: dict) -> None:
        """
        Envoie un message à tous les clients connectés.

        FIX: sérialisation du JSON effectuée une seule fois avant le gather,
        puis transmission de la chaîne déjà sérialisée via _safe_send().
        L'asymétrie _send(dict) / _safe_send(str) est désormais documentée
        intentionnellement : broadcast sérialise une fois pour tous les clients.

        Args:
            payload: Message à diffuser.
        """
        if not self._clients:
            return

        msg = json.dumps(payload, ensure_ascii=False)
        await asyncio.gather(
            *[self._safe_send(c.ws, msg) for c in self._clients.values()],
            return_exceptions=True,
        )

    async def _safe_send(self, ws: ServerConnection, msg: str) -> None:
        """
        Envoie une chaîne JSON déjà sérialisée en ignorant les déconnexions.

        Utilisé exclusivement par broadcast() pour éviter N sérialisations.

        Args:
            ws:  Socket du client.
            msg: Chaîne JSON déjà sérialisée.
        """
        try:
            await ws.send(msg)
        except ConnectionClosed:
            pass

    # ── Propriétés utilitaires ─────────────────────────────────────────────

    @property
    def client_count(self) -> int:
        """Nombre de clients actuellement connectés."""
        return len(self._clients)

    @property
    def is_auth_enabled(self) -> bool:
        """Indique si l'authentification est activée."""
        return self.config.token is not None


# ──────────────────────────────────────────────────────────────────────────────
# Helpers frames JSON-RPC
# ──────────────────────────────────────────────────────────────────────────────


def _result(req_id: Any, data: dict) -> dict:
    """Construit une réponse JSON-RPC 2.0 de succès."""
    return {"id": req_id, "result": data}


def _error(req_id: Any, code: int, message: str) -> dict:
    """Construit une réponse JSON-RPC 2.0 d'erreur."""
    return {"id": req_id, "error": {"code": code, "message": message}}


def _event(name: str, data: dict) -> dict:
    """Construit une notification d'event (sans id)."""
    return {"event": name, "data": data}


# ──────────────────────────────────────────────────────────────────────────────
# Point d'entrée standalone
# ──────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    """Point d'entrée pour lancer le gateway en tant que script."""
    import os

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    config = GatewayConfig(
        host=os.getenv("NERON_HOST", DEFAULT_HOST),
        port=int(os.getenv("NERON_PORT", str(DEFAULT_PORT))),
        token=os.getenv("NERON_TOKEN"),
    )

    gw = NeronGateway(config=config)
    await gw.start()


if __name__ == "__main__":
    asyncio.run(main())
