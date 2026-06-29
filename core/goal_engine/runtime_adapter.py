from __future__ import annotations

from typing import Any

from core.a2a import A2AClient, AgentCard, AgentResponse, AgentTask
from core.providers.models import ProviderRequest
from core.providers.registry import ProviderRegistry


def register_runtime_handler(
    card: AgentCard,
    a2a: A2AClient,
    providers: ProviderRegistry,
    runtime: Any,
) -> None:
    async def handler(task: AgentTask) -> AgentResponse:
        context: dict[str, Any] = {}
        if "weather" in card.capabilities:
            provider_infos = [
                info for info in providers.by_type("web")
                if "current_weather" in info.capabilities
            ]
            provider = providers.get(provider_infos[0].name) if provider_infos else None
            if provider is None:
                return AgentResponse(
                    task_id=task.task_id,
                    agent_id=card.agent_id,
                    status="failed",
                    error="weather provider unavailable",
                    trace_id=task.trace_id,
                )
            weather = await provider.execute(
                ProviderRequest(
                    action="current_weather",
                    payload={"location": "Paris"},
                    trace_id=task.trace_id,
                )
            )
            if weather.error:
                return AgentResponse(
                    task_id=task.task_id,
                    agent_id=card.agent_id,
                    status="failed",
                    error=weather.error,
                    trace_id=task.trace_id,
                )
            context["weather"] = weather.result

        execution = await runtime.run_agent(
            card.agent_id,
            _task_text(task),
            context=context,
            metadata={"a2a_task_id": task.task_id, "goal_id": task.payload.get("goal_id")},
        )
        if not execution.ok:
            return AgentResponse(
                task_id=task.task_id,
                agent_id=card.agent_id,
                status="failed",
                error=execution.error,
                trace_id=task.trace_id,
            )
        return AgentResponse(
            task_id=task.task_id,
            agent_id=card.agent_id,
            status="completed",
            result={
                **execution.result,
                "agent_response": execution.response,
                "execution_id": execution.execution_id,
                "sandbox_used": execution.sandbox_used,
                "sandbox_backend": execution.sandbox_backend,
            },
            trace_id=task.trace_id,
        )

    a2a.register_handler(card, handler)


def _task_text(task: AgentTask) -> str:
    return next(
        (message.content for message in reversed(task.messages) if message.role == "user"),
        str(task.payload.get("objective") or ""),
    )
