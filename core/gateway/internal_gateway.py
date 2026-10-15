# core/gateway/internal_gateway.py
# Point d'entrée unique vers le pipeline Néron.
# Tous les gateways externes (WebSocket, Telegram, HTTP) passent ici.

from __future__ import annotations

import logging
from typing import AsyncIterator

from core.pipeline.intent.intent_router import IntentRouter
from core.pipeline.orchestrator import CoreOrchestrator
from core.pipeline.routing.agent_router import AgentRouter

logger = logging.getLogger("neron.gateway.internal")


class InternalGateway:
    """
    Façade unique vers le pipeline Néron.
    Reçoit du texte brut, retourne une réponse ou un flux de tokens.
    """

    def __init__(
        self,
        agent_router: AgentRouter,
        intent_router: IntentRouter | None = None,
    ) -> None:
        self.agent_router = agent_router
        self.intent_router = intent_router or IntentRouter()
        self.orchestrator = CoreOrchestrator(
            intent_router=self.intent_router,
            agent_router=self.agent_router,
        )

    # ─────────────────────────────────────────────
    # API PUBLIQUE
    # ─────────────────────────────────────────────

    async def handle_text(self, text: str, session_id: str = "default") -> str:
        """
        Traite un texte et retourne la réponse complète (non-streaming).
        Utilisé par HTTP gateway et Telegram pour les requêtes code.
        """
        result = await self.orchestrator.handle(
            text,
            session_id=session_id,
            source_channel="internal_gateway",
        )
        return result.response

    async def stream(
        self, text: str, session_id: str = "default"
    ) -> AsyncIterator[str]:
        """
        Streame les tokens de la réponse LLM.
        Utilisé par WebSocket gateway et Telegram pour la conversation.
        """
        result = await self.orchestrator.handle(
            text,
            session_id=session_id,
            source_channel="internal_gateway",
        )
        yield result.response

    async def run_agent(
        self, text: str, session_id: str = "default"
    ) -> AsyncIterator[dict]:
        """
        Agent loop complet avec tool-use.
        Yield des events {event, data}.
        """
        async for event in self.agent_router.run_stream(session_id, text):
            yield event
