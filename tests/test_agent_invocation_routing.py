from __future__ import annotations

import pytest

# NERONOS PHASE 2A — test lourd.
# ~18 s — routage d invocation, runtime d agents reel.
# Exclu par defaut (pytest.ini : addopts = -m "not slow").
# Pour l executer : pytest -m slow
# L intention fonctionnelle est intacte : seul le declenchement change.
pytestmark = pytest.mark.slow


from types import SimpleNamespace

import pytest

from core.pipeline.orchestrator import CoreOrchestrator


class FakeRuntime:
    def __init__(self, *, agents=None, response="Goal Engine OK", error=None):
        self.agents = list(
            ["validation_goal_engine"] if agents is None else agents
        )
        self.response = response
        self.error = error
        self.calls = []

    def reload(self):
        return {"ok": True, "count": len(self.agents), "agents": self.agents}

    async def run_agent(self, slug, request, metadata=None):
        self.calls.append((slug, request, metadata))
        ok = self.error is None
        return SimpleNamespace(
            agent_slug=slug,
            status="completed" if ok else "failed",
            response=self.response if ok else "",
            error=self.error,
            ok=ok,
            sandbox_used=True,
            sandbox_backend="systemd",
            sandbox_isolation="kernel_systemd",
            sudo_used=True,
            to_dict=lambda: {
                "agent_slug": slug,
                "status": "completed" if ok else "failed",
                "response": self.response if ok else "",
                "error": self.error,
                "ok": ok,
            },
        )


class ForbiddenAgentRouter:
    async def route(self, *_args, **_kwargs):
        raise AssertionError("Explicit agent invocation must not use the LLM")


@pytest.mark.asyncio
async def test_agent_invocation_routes_to_runtime():
    runtime = FakeRuntime()
    orchestrator = CoreOrchestrator(
        agent_router=ForbiddenAgentRouter(),
        agent_runtime_factory=lambda: runtime,
    )

    result = await orchestrator.handle("Lance validation_goal_engine")

    assert result.decision.selected_route == "registered_agent_runtime"
    assert result.executor == "agent_runtime"
    assert result.decision.requires_llm is False
    assert runtime.calls[0][0] == "validation_goal_engine"


@pytest.mark.asyncio
async def test_agent_invocation_does_not_use_llm():
    runtime = FakeRuntime()
    result = await CoreOrchestrator(
        agent_router=ForbiddenAgentRouter(),
        agent_runtime_factory=lambda: runtime,
    ).handle("Exécute l’agent validation_goal_engine")

    assert result.error is None
    assert result.metadata["registry_lookup"] == "found"
    assert result.metadata["runtime_status"] == "completed"
    assert result.metadata["sandbox_used"] is True
    assert result.metadata["sandbox_backend"] == "systemd"
    assert result.metadata["sandbox_isolation"] == "kernel_systemd"
    assert result.metadata["sudo_used"] is True


@pytest.mark.asyncio
async def test_agent_invocation_returns_real_agent_output():
    runtime = FakeRuntime(response="Goal Engine OK")
    result = await CoreOrchestrator(
        agent_router=ForbiddenAgentRouter(),
        agent_runtime_factory=lambda: runtime,
    ).handle(
        "/agent run validation_goal_engine --input 'message réel'",
        request_metadata={"request_id": "test"},
    )

    assert result.response == "Goal Engine OK"
    assert result.metadata["invoked_agent"] == "validation_goal_engine"
    assert runtime.calls[0][1] == "message réel"


@pytest.mark.asyncio
async def test_agent_invocation_unknown_agent_returns_clear_error():
    runtime = FakeRuntime(agents=[])
    result = await CoreOrchestrator(
        agent_router=ForbiddenAgentRouter(),
        agent_runtime_factory=lambda: runtime,
    ).handle("Demande à missing_agent de répondre")

    assert result.response == "Agent introuvable : missing_agent"
    assert result.error == "Agent introuvable : missing_agent"
    assert result.metadata["registry_lookup"] == "not_found"
    assert result.metadata["runtime_status"] == "not_started"
    assert runtime.calls == []


@pytest.mark.asyncio
async def test_create_agent_is_left_to_the_manager():
    decision, _ = await CoreOrchestrator().decide(
        "Crée un agent nommé validation_goal_engine"
    )

    assert decision.selected_route == "manager_delegation"
    assert decision.requires_goal_pipeline is True


@pytest.mark.asyncio
async def test_llm_does_not_fake_agent_delegation():
    runtime = FakeRuntime(response="sortie réelle")
    result = await CoreOrchestrator(
        agent_router=ForbiddenAgentRouter(),
        agent_runtime_factory=lambda: runtime,
    ).handle("Demande à validation_goal_engine : réponds maintenant")

    assert result.response == "sortie réelle"
    assert result.executor == "agent_runtime"
    assert result.metadata["invoked_agent"] == "validation_goal_engine"
    assert runtime.calls[0][1] == "réponds maintenant"


@pytest.mark.asyncio
async def test_registered_agent_invocation_sandbox_error_no_llm_fallback():
    runtime = FakeRuntime(error="agent_sandbox_timeout")
    result = await CoreOrchestrator(
        agent_router=ForbiddenAgentRouter(),
        agent_runtime_factory=lambda: runtime,
    ).handle("Lance validation_goal_engine")

    assert result.error == "agent_sandbox_timeout"
    assert result.decision.requires_llm is False
    assert result.fallback_used is False
    assert result.metadata["sandbox_used"] is True


@pytest.mark.asyncio
async def test_unknown_agent_no_llm_fallback():
    runtime = FakeRuntime(agents=[])
    result = await CoreOrchestrator(
        agent_router=ForbiddenAgentRouter(),
        agent_runtime_factory=lambda: runtime,
    ).handle("Lance unknown_phase4_agent")

    assert result.error == "Agent introuvable : unknown_phase4_agent"
    assert result.decision.requires_llm is False
    assert result.fallback_used is False
    assert result.metadata["registry_lookup"] == "not_found"
