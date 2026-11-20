# agents/builtin/io/voice_proxy.py
# NéronOS - Proxies HTTP vers le microservice voice (server/voice/app.py, port 8045)
#
# Même interface que STTAgent/TTSAgent (transcribe/synthesize/reload/check_connection,
# retour AgentResult) pour que gateway.py et le reste du code n'aient rien à changer.

from __future__ import annotations

import base64
import os
import time

import httpx

from agents.builtin.base_agent import AgentResult, get_logger

logger = get_logger("voice_proxy")

# Le service voice ecoute sur son alias loopback dedie (nodes.voice de
# neron.server.yaml), pas sur 127.0.0.1. Surchargeable par NERON_VOICE_URL.
VOICE_SERVICE_BASE_URL = os.getenv("NERON_VOICE_URL", "http://127.0.1.5:8045")


def _auth_headers() -> dict[str, str]:
    """Authorization: Bearer <NERON_API_KEY>, exigé par le service depuis
    l'ajout de son authentification (lu à chaque appel)."""
    from server.common.auth import api_key_headers

    return api_key_headers(os.getenv("NERON_API_KEY", "").strip())


_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


class STTAgentProxy:
    def __init__(self, base_url: str = VOICE_SERVICE_BASE_URL):
        self._base_url = base_url.rstrip("/")

    async def transcribe(self, audio_bytes: bytes, filename: str) -> AgentResult:
        start = time.monotonic()
        payload = {
            "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
            "filename": filename,
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_auth_headers()) as client:
                resp = await client.post(f"{self._base_url}/transcribe", json=payload)
            resp.raise_for_status()
            data = resp.json()

            return AgentResult(
                success=data.get("success", False),
                content=data.get("text") or "",
                source="stt_agent",
                error=data.get("error"),
                latency_ms=data.get("latency_ms", round((time.monotonic() - start) * 1000, 2)),
                metadata=data.get("metadata", {}),
            )
        except Exception as e:
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            logger.error(f"Erreur appel voice service (transcribe) : {e}")
            return AgentResult(
                success=False, content="", source="stt_agent",
                error=f"Voice service indisponible : {e}",
                latency_ms=latency_ms, metadata={},
            )

    async def reload(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_auth_headers()) as client:
                resp = await client.post(f"{self._base_url}/reload")
            resp.raise_for_status()
            return bool(resp.json().get("stt_reloaded", False))
        except Exception as e:
            logger.error(f"STT reload (proxy) error: {e}")
            return False

    async def check_connection(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0), headers=_auth_headers()) as client:
                resp = await client.get(f"{self._base_url}/health")
            resp.raise_for_status()
            return bool(resp.json().get("stt_ready", False))
        except Exception:
            return False


class TTSAgentProxy:
    def __init__(self, base_url: str = VOICE_SERVICE_BASE_URL):
        self._base_url = base_url.rstrip("/")

    async def synthesize(self, text: str) -> AgentResult:
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_auth_headers()) as client:
                resp = await client.post(f"{self._base_url}/synthesize", json={"text": text})

            if resp.status_code != 200:
                detail = resp.text
                try:
                    detail = resp.json().get("detail", detail)
                except Exception:
                    pass
                return AgentResult(
                    success=False, content="", source="tts_agent",
                    error=detail,
                    latency_ms=round((time.monotonic() - start) * 1000, 2),
                    metadata={},
                )

            audio_bytes = resp.content
            mimetype = resp.headers.get("content-type", "audio/mpeg")
            latency_ms = round((time.monotonic() - start) * 1000, 2)

            return AgentResult(
                success=True, content="", source="tts_agent",
                error=None, latency_ms=latency_ms,
                metadata={
                    "audio_bytes": audio_bytes,
                    "mimetype": mimetype,
                    "engine": "voice_service",
                    "chars": len(text),
                },
            )
        except Exception as e:
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            logger.error(f"Erreur appel voice service (synthesize) : {e}")
            return AgentResult(
                success=False, content="", source="tts_agent",
                error=f"Voice service indisponible : {e}",
                latency_ms=latency_ms, metadata={},
            )

    async def reload(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_auth_headers()) as client:
                resp = await client.post(f"{self._base_url}/reload")
            resp.raise_for_status()
            return bool(resp.json().get("tts_reloaded", False))
        except Exception as e:
            logger.error(f"TTS reload (proxy) error: {e}")
            return False

    async def check_connection(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0), headers=_auth_headers()) as client:
                resp = await client.get(f"{self._base_url}/health")
            resp.raise_for_status()
            return bool(resp.json().get("tts_ready", False))
        except Exception:
            return False
