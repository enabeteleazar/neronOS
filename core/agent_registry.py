from __future__ import annotations

import importlib
import logging
from typing import Any, Callable


logger = logging.getLogger("core.agent_registry")


class NullAgent:
    """Compatibility placeholder used when an external agent is unavailable."""

    name = "unavailable-agent"

    async def check_connection(self) -> bool:
        return False

    async def on_start(self) -> None:
        return None

    async def on_stop(self) -> None:
        return None

    async def retrieve(self, limit: int = 5) -> list[Any]:
        return []

    async def transcribe(self, *_args: Any, **_kwargs: Any) -> Any:
        return _Result(success=False, error="STT agent unavailable")

    async def synthesize(self, *_args: Any, **_kwargs: Any) -> Any:
        return _Result(success=False, error="TTS agent unavailable")

    async def reload(self) -> int:
        return 0


class _Result:
    def __init__(self, *, success: bool, error: str = "", content: str = "") -> None:
        self.success = success
        self.error = error
        self.content = content
        self.latency_ms = 0
        self.metadata: dict[str, Any] = {}


async def noop_async(*_args: Any, **_kwargs: Any) -> None:
    return None


def noop(*_args: Any, **_kwargs: Any) -> None:
    return None


def get_logger(name: str) -> logging.Logger:
    try:
        module = importlib.import_module("agents.builtin.base_agent")
        return module.get_logger(name)
    except Exception:
        return logging.getLogger(name)


class AgentRegistry:
    """Lazy loader for external application agents."""

    def load(self, module_name: str, attribute: str, *, default: Any = None) -> Any:
        try:
            module = importlib.import_module(module_name)
            return getattr(module, attribute)
        except Exception as exc:
            logger.warning(
                "External agent dependency unavailable: %s.%s (%s)",
                module_name,
                attribute,
                exc,
            )
            return default

    def agent_class(self, module_name: str, attribute: str) -> type:
        return self.load(module_name, attribute, default=NullAgent)

    def function(self, module_name: str, attribute: str, *, async_default: bool = False) -> Callable:
        return self.load(
            module_name,
            attribute,
            default=noop_async if async_default else noop,
        )


agent_registry = AgentRegistry()


def get_external_agent_registry() -> AgentRegistry:
    return agent_registry
