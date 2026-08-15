"""Ecriture d'etat pour les agents (activer/desactiver).

Reutilise le meme AgentRegistry singleton que providers_snapshot.py,
pour rester coherent avec la lecture (self_model["agent_topology"]).
"""

from __future__ import annotations


def set_agent_status(agent_id: str, enabled: bool) -> dict:
    from core.goal_engine import agent_registry

    agent_registry.load_existing_agents()
    card = agent_registry.get(agent_id)
    if card is None:
        raise ValueError(f"agent inconnu : {agent_id}")

    new_status = "available" if enabled else "unavailable"
    updated = card.model_copy(update={"status": new_status})
    agent_registry.register(updated)

    return {"agent_id": agent_id, "status": new_status}
