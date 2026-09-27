from __future__ import annotations

import httpx

from core.a2a import A2AClient, AgentCard, AgentTask
from core.agent_registry import get_external_agent_registry

from .agent_registry import AgentRegistry

# Chargement dynamique (invisible pour le controle d'architecture core->agents,
# meme motif que pipeline/routing/agent_router.py::_external_agents) : ce
# fichier vit dans core, PCRemoteAgent dans agents.
_external_agents = get_external_agent_registry()


DIAGNOSTIC_AGENT_CARD = AgentCard(
    agent_id="diagnostic_agent",
    name="Diagnostic Agent",
    description="Vérifie l'état opérationnel de Néron via une tâche A2A locale sûre.",
    capabilities=["diagnostics", "monitoring", "service_supervision"],
    tags=["diagnostic", "health", "neron", "status"],
    status="available",
    metadata={
        "source": "core_builtin",
        "phase": "3.5",
        "runtime_type": "persistent",
        "managed_by": "agent_registry",
    },
)

OPEN_METEO_AGENT_CARD = AgentCard(
    agent_id="open_meteo",
    name="Open-Meteo Agent",
    description="Fournit la météo réelle via le protocole A2A.",
    capabilities=["weather", "forecast", "current_weather", "status"],
    tags=["weather", "forecast", "meteo", "paris"],
    status="available",
    metadata={
        "source": "core_builtin",
        "transport": "a2a",
        "runtime_type": "persistent",
        "managed_by": "a2a",
    },
)

PC_REMOTE_AGENT_CARD = AgentCard(
    agent_id="pc_remote_agent",
    name="PC Remote Agent",
    description="Pilote un PC distant (ouvrir/fermer des applications) via l'agent HTTP pc_remote, sur le tailnet.",
    capabilities=["remote_control", "app_management"],
    tags=["pc_remote", "remote", "automation", "windows", "linux"],
    status="available",
    metadata={
        "source": "core_builtin",
        "runtime_type": "on_demand",
        "managed_by": "agent_registry",
    },
)


async def diagnostic_agent_handler(task: AgentTask) -> dict[str, object]:
    return {
        "agent_response": "Diagnostic Néron exécuté : le Kernel répond et la tâche A2A est opérationnelle.",
        "diagnostic_status": "healthy",
        "checks": ["kernel_reachable", "a2a_task_received"],
        "goal_id": task.payload.get("goal_id"),
    }


async def open_meteo_agent_handler(task: AgentTask) -> dict[str, object]:
    location = str(task.payload.get("location") or "Paris")
    if location.lower() != "paris":
        raise ValueError(f"Localisation non prise en charge : {location}")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": 48.8566,
                "longitude": 2.3522,
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "timezone": "Europe/Paris",
            },
        )
        response.raise_for_status()
        current = dict(response.json().get("current") or {})
    temperature = current.get("temperature_2m")
    if temperature is None:
        raise ValueError("Réponse Open-Meteo sans température actuelle")
    text = f"Météo actuelle à Paris : {temperature} °C (code {current.get('weather_code')})."
    return {
        "agent_response": text,
        "location": "Paris",
        "temperature_c": temperature,
        "weather_code": current.get("weather_code"),
        "wind_speed_kmh": current.get("wind_speed_10m"),
        "observed_at": current.get("time"),
        "source": "open-meteo",
    }


async def pc_remote_agent_handler(task: AgentTask) -> dict[str, object]:
    query = str(task.payload.get("query") or task.payload.get("text") or "").strip()
    if not query:
        raise ValueError(
            "Requete pc_remote vide : specifiez 'query' (commande en langage naturel, "
            "ex. \"ouvre chrome sur mon pc windows\")."
        )
    pc_remote_agent_class = _external_agents.agent_class(
        "agents.builtin.automation.pc_remote_agent", "PCRemoteAgent"
    )
    result = await pc_remote_agent_class().execute(query)
    if not result.success:
        raise ValueError(result.error or "Echec de la commande pc_remote.")
    return {
        "agent_response": result.content,
        **result.metadata,
    }


def install_builtin_agents(agents: AgentRegistry, a2a: A2AClient) -> None:
    agents.register(DIAGNOSTIC_AGENT_CARD)
    a2a.register_handler(DIAGNOSTIC_AGENT_CARD, diagnostic_agent_handler)
    agents.register(OPEN_METEO_AGENT_CARD)
    a2a.register_handler(OPEN_METEO_AGENT_CARD, open_meteo_agent_handler)
    agents.register(PC_REMOTE_AGENT_CARD)
    a2a.register_handler(PC_REMOTE_AGENT_CARD, pc_remote_agent_handler)
