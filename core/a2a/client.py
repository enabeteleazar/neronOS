from __future__ import annotations

from threading import RLock
from typing import Iterable

from .models import AgentCard, AgentResponse, AgentTask


class A2AClient:
    """Minimal local/mock A2A client for Kernel-to-agent communication."""

    def __init__(self, agents: Iterable[AgentCard] | None = None) -> None:
        self._lock = RLock()
        self._agents: dict[str, AgentCard] = {}
        for agent in agents or []:
            self.register_agent(agent)

    def register_agent(self, card: AgentCard) -> AgentCard:
        with self._lock:
            self._agents[card.agent_id] = card
        return card

    def get_agent(self, agent_id: str) -> AgentCard | None:
        with self._lock:
            return self._agents.get(agent_id)

    def list_agents(self) -> list[AgentCard]:
        with self._lock:
            return list(self._agents.values())

    async def health(self) -> dict[str, object]:
        agents = self.list_agents()
        return {
            "status": "available",
            "mode": "local_mock",
            "agent_count": len(agents),
            "agents": [agent.model_dump(mode="json") for agent in agents],
        }

    async def send_task(self, task: AgentTask) -> AgentResponse:
        agent = self.get_agent(task.target_agent)
        if agent is None:
            return AgentResponse(
                task_id=task.task_id,
                agent_id=task.target_agent,
                status="failed",
                error="agent not found",
                trace_id=task.trace_id,
            )

        return AgentResponse(
            task_id=task.task_id,
            agent_id=agent.agent_id,
            status="accepted",
            result={
                "mode": "local_mock",
                "message_count": len(task.messages),
                "capabilities": agent.capabilities,
            },
            trace_id=task.trace_id,
        )

    def status(self) -> dict[str, object]:
        agents = self.list_agents()
        return {
            "available": True,
            "mode": "local_mock",
            "agent_count": len(agents),
            "agents": [agent.model_dump(mode="json") for agent in agents],
        }


a2a_client = A2AClient(
    agents=[
        AgentCard(
            agent_id="local_mock",
            name="Local Mock Agent",
            capabilities=["health", "send_task"],
            status="available",
        )
    ]
)
