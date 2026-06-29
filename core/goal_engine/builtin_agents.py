from __future__ import annotations

from core.a2a import A2AClient, AgentCard, AgentTask

from .agent_registry import AgentRegistry


DIAGNOSTIC_AGENT_CARD = AgentCard(
    agent_id="diagnostic_agent",
    name="Diagnostic Agent",
    description="Vérifie l'état opérationnel de Néron via une tâche A2A locale sûre.",
    capabilities=["diagnostics", "monitoring", "service_supervision"],
    tags=["diagnostic", "health", "neron", "status"],
    status="available",
    metadata={"source": "core_builtin", "phase": "3.5"},
)


async def diagnostic_agent_handler(task: AgentTask) -> dict[str, object]:
    return {
        "agent_response": "Diagnostic Néron exécuté : le Kernel répond et la tâche A2A est opérationnelle.",
        "diagnostic_status": "healthy",
        "checks": ["kernel_reachable", "a2a_task_received"],
        "goal_id": task.payload.get("goal_id"),
    }


def install_builtin_agents(agents: AgentRegistry, a2a: A2AClient) -> None:
    agents.register(DIAGNOSTIC_AGENT_CARD)
    a2a.register_handler(DIAGNOSTIC_AGENT_CARD, diagnostic_agent_handler)
