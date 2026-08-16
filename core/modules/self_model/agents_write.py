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


def delete_agent(agent_id: str) -> dict:
    import os
    from pathlib import Path

    from core.goal_engine import agent_registry

    agent_registry.load_existing_agents()
    card = agent_registry.get(agent_id)
    if card is None:
        raise ValueError(f"agent inconnu : {agent_id}")

    removed_files: list[str] = []
    path_hint = card.metadata.get("path") if isinstance(card.metadata, dict) else None
    candidates = []
    if path_hint:
        candidates.append(Path(path_hint))
    generated_dir = Path("/etc/neronOS/data/generated_agents")
    candidates.append(generated_dir / f"{agent_id}.py")
    candidates.append(generated_dir / f"{agent_id}.manifest.json")

    for candidate in candidates:
        try:
            if candidate.exists():
                os.remove(candidate)
                removed_files.append(str(candidate))
        except OSError:
            pass

    with agent_registry._lock:
        agent_registry._agents.pop(agent_id, None)

    return {"agent_id": agent_id, "deleted": True, "removed_files": removed_files}
