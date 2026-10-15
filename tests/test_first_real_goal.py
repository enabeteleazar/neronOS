from __future__ import annotations

from pathlib import Path

import pytest

from goal_engine import AgentCreationRequest, AgentFactory, GoalEngine, GoalRequest
from core.providers.models import ProviderRequest, ProviderResponse
from core.providers.registry import ProviderRegistry


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


GENERATED_SOURCE = """
class Agent:
    name = "weather_agent"
    capabilities = ["agent_creation", "forecast", "weather"]

    async def execute(self, text: str = "", context: dict | None = None) -> dict:
        weather = (context or {}).get("weather", {})
        location = weather.get("location", "Paris")
        temperature = weather.get("temperature_c")
        return {
            "status": "ok",
            "agent": self.name,
            "source": weather.get("source"),
            "temperature_c": temperature,
            "weather_code": weather.get("weather_code"),
            "response": f"Météo actuelle à {location} : {temperature} °C.",
        }
"""


class GeneratedLLMProvider:
    name = "llm-test"
    type = "llm"
    status = "healthy"
    capabilities = ["generate"]

    async def health(self):
        return ProviderResponse(provider=self.name, action="health", status="healthy")

    async def execute(self, request: ProviderRequest):
        return ProviderResponse(
            provider=self.name,
            action=request.action,
            status="healthy",
            result={"text": GENERATED_SOURCE, "model": "test-code-model"},
        )


async def test_factory_generates_validated_artifacts_from_llm_provider(tmp_path: Path):
    providers = ProviderRegistry()
    providers.register(GeneratedLLMProvider())
    engine = GoalEngine(providers=providers)
    analysis = await engine.analyze(GoalRequest(objective="Crée un agent météo."))
    factory = AgentFactory()
    plan = factory.create_plan(AgentCreationRequest(goal_analysis=analysis))

    artifacts = await factory.generate_supervised(
        plan,
        providers,
        generated_dir=tmp_path / "agents",
        tests_dir=tmp_path / "tests",
    )
    artifacts = await factory.validate_artifacts(artifacts)

    assert plan.spec.name == "weather_agent"
    assert plan.spec.validation_task == "Météo actuelle à Paris"
    assert artifacts.test_passed is True
    assert Path(artifacts.agent_file).exists()
    assert Path(artifacts.manifest_file).exists()
