from __future__ import annotations

import httpx

from core.a2a import A2AClient, AgentCard, AgentTask

from .agent_registry import AgentRegistry


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


def install_builtin_agents(agents: AgentRegistry, a2a: A2AClient) -> None:
    agents.register(DIAGNOSTIC_AGENT_CARD)
    a2a.register_handler(DIAGNOSTIC_AGENT_CARD, diagnostic_agent_handler)
    agents.register(OPEN_METEO_AGENT_CARD)
    a2a.register_handler(OPEN_METEO_AGENT_CARD, open_meteo_agent_handler)
