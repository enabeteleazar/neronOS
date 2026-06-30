from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SelfModelGoalContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    error: str | None = None
    status: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    providers: dict[str, Any] = Field(default_factory=dict)
    agents: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    architecture: dict[str, Any] = Field(default_factory=dict)


class SelfModelClient:
    """Internal read-only client for the canonical SelfModel."""

    async def load(self) -> SelfModelGoalContext:
        try:
            from core.modules.self_model import get_self_model

            model = get_self_model()
            model.refresh()
            data = model.to_dict()
            return SelfModelGoalContext(
                available=True,
                status={
                    "health": data.get("health", {}),
                    "runtime_mode": data.get("runtime_mode"),
                    "diagnostics": data.get("diagnostics", []),
                },
                capabilities=dict(data.get("capabilities") or {}),
                providers=dict(data.get("providers") or {}),
                agents={
                    "registry": dict(data.get("agents") or {}),
                    "a2a": dict(data.get("a2a") or {}),
                },
                memory=dict(data.get("memory") or {}),
                architecture=dict(data.get("architecture") or {}),
            )
        except Exception as exc:
            return SelfModelGoalContext(available=False, error=str(exc))


self_model_client = SelfModelClient()
