from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ProviderType = Literal[
    "memory",
    "knowledge",
    "llm",
    "homeassistant",
    "git",
    "web",
    "notification",
    "generic",
]

ProviderStatus = Literal["healthy", "degraded", "unhealthy", "unavailable", "unknown"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProviderInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: ProviderType
    status: ProviderStatus = "unknown"
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    registered_at: datetime = Field(default_factory=utc_now)
    last_seen: datetime = Field(default_factory=utc_now)


class ProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None


class ProviderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    action: str
    status: ProviderStatus
    result: Any = None
    error: str | None = None
    trace_id: str | None = None
