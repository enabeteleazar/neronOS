from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    endpoint: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    status: Literal["available", "unavailable", "unknown"] = "unknown"


class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"] = "user"
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    target_agent: str = Field(min_length=1)
    messages: list[AgentMessage] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    agent_id: str
    status: Literal["accepted", "completed", "failed"]
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    trace_id: str | None = None
    completed_at: datetime = Field(default_factory=utc_now)
