from __future__ import annotations

from typing import Any

from agents.builtin.base_agent import AgentResult, BaseAgent
from integrations.pc_remote.errors import PCRemoteError
from integrations.pc_remote.service import PCRemoteService, get_pc_remote_service


class PCRemoteAgent(BaseAgent):
    """Facade agent au-dessus de l'integration pc_remote (controle PC distant)."""

    def __init__(self, service: PCRemoteService | None = None) -> None:
        super().__init__(name="pc_remote_agent")
        self.service = service or get_pc_remote_service()

    async def execute(self, query: str, **kwargs: Any) -> AgentResult:
        del kwargs
        start = self._timer()
        try:
            result = await self.service.execute_natural(query)
            return self._success(
                content=str(result.get("response") or "Action pc_remote exécutée."),
                metadata=result,
                latency_ms=self._elapsed_ms(start),
                confidence="high",
            )
        except PCRemoteError as exc:
            return self._failure(exc.user_message, latency_ms=self._elapsed_ms(start))
        except Exception as exc:
            self.logger.exception("[pc_remote] unexpected_error")
            return self._failure(f"Erreur PC distant : {exc}", latency_ms=self._elapsed_ms(start))
