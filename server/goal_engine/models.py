from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.a2a import AgentResponse


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


GoalStatus = Literal[
    "received",
    "analyzed",
    "agent_found",
    "agent_creation_required",
    "execution_prepared",
    "verified",
    "failed",
    "completed",
    "blocked",
    "needs_agent_creation",
]


class GoalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1)
    goal_id: str = Field(default_factory=lambda: str(uuid4()))
    source: str = "api"
    user_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class GoalAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: str
    objective: str
    summary: str
    required_capabilities: list[str] = Field(default_factory=list)
    complexity: Literal["simple", "medium", "complex"] = "medium"
    llm_used: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class GoalPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: str
    objective: str
    status: GoalStatus
    analysis: GoalAnalysis
    steps: list[str] = Field(default_factory=list)
    agent_id: str | None = None
    agent_found: bool = False
    agent_creation_required: bool = False
    a2a_task_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GoalExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    goal_id: str
    status: GoalStatus
    plan: GoalPlan
    agent_found: bool = False
    agent_creation_required: bool = False
    a2a_used: bool = False
    a2a_response: AgentResponse | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class GoalVerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: str
    status: Literal["verified", "pending", "failed"]
    ok: bool
    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class GoalEngineResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: str
    goal_status: GoalStatus
    analysis: GoalAnalysis
    plan: GoalPlan
    execution: GoalExecutionResult
    verification: GoalVerificationResult
    response: str
    agent_found: bool
    agent_creation_required: bool
    memory_learned: bool = False
    llm_used: bool = False
    a2a_used: bool = False
    agent_creation_plan: dict[str, Any] | None = None
    loop_iterations: int = 0
    next_action: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_orchestrator_metadata(self) -> dict[str, Any]:
        return {
            "selected_route": "goal_engine",
            "executor": "goal_engine",
            "goal_id": self.goal_id,
            "goal_status": self.goal_status,
            "agent_found": self.agent_found,
            "agent_creation_required": self.agent_creation_required,
            "verification_status": self.verification.status,
            "memory_learned": self.memory_learned,
            "llm_used": self.llm_used,
            "a2a_used": self.a2a_used,
            "agent_creation_plan": self.agent_creation_plan,
            "loop_iterations": self.loop_iterations,
            "next_action": self.next_action,
            "agent_response": (
                self.execution.a2a_response.result
                if self.execution.a2a_response is not None
                else None
            ),
            "goal_analysis": self.analysis.model_dump(mode="json"),
            "goal_plan": self.plan.model_dump(mode="json"),
            "goal_execution": self.execution.model_dump(mode="json"),
            "goal_verification": self.verification.model_dump(mode="json"),
            **self.metadata,
        }
