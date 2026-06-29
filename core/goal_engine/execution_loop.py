from __future__ import annotations

import inspect
import os
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


LoopState = Literal[
    "pending",
    "analyzing",
    "planning",
    "executing",
    "verifying",
    "fixing",
    "completed",
    "blocked",
    "needs_agent_creation",
]


class GoalLoopResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: LoopState
    iterations: int
    result: Any = None
    verification: Any = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    reason: str | None = None
    next_action: str | None = None


class GoalExecutionLoop:
    """Bounded work → verify → fix loop with no autonomous side effects."""

    def __init__(self, max_iterations: int | None = None) -> None:
        configured = max_iterations or int(os.getenv("NERON_GOAL_MAX_ITERATIONS", "3"))
        self.max_iterations = max(1, configured)

    async def run(
        self,
        execute: Callable[[int], Any | Awaitable[Any]],
        verify: Callable[[Any], Any | Awaitable[Any]],
        fix: Callable[[Any, Any, int], Any | Awaitable[Any]] | None = None,
    ) -> GoalLoopResult:
        history: list[dict[str, Any]] = []
        result: Any = None
        verification: Any = None
        for iteration in range(1, self.max_iterations + 1):
            result = await _resolve(execute(iteration))
            verification = await _resolve(verify(result))
            ok = bool(
                verification.get("ok")
                if isinstance(verification, dict)
                else getattr(verification, "ok", False)
            )
            history.append(
                {
                    "iteration": iteration,
                    "states": ["executing", "verifying"],
                    "verified": ok,
                }
            )
            if ok:
                return GoalLoopResult(
                    status="completed",
                    iterations=iteration,
                    result=result,
                    verification=verification,
                    history=history,
                )
            if iteration < self.max_iterations and fix is not None:
                await _resolve(fix(result, verification, iteration))
                history[-1]["states"].append("fixing")

        return GoalLoopResult(
            status="blocked",
            iterations=self.max_iterations,
            result=result,
            verification=verification,
            history=history,
            reason="Nombre maximal d'itérations atteint sans vérification concluante.",
            next_action="Réviser le plan ou fournir une capacité/validation supplémentaire.",
        )


async def _resolve(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
