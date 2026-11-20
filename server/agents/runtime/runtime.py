from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any

from agents.factory.registry import DynamicAgentRegistry
from agents.runtime.models import (
    AgentExecutionResult,
    AgentInstance,
    ExecutionContext,
    ToolBinding,
    utc_now_iso,
)
from agents.runtime.store import AgentRuntimeStore
from server.common.runtime.sandbox.agent_sandbox import AgentSandbox
from modules.events.event import Event
from modules.events.event_bus import event_bus
from modules.events.event_types import (
    AGENT_EXECUTION_COMPLETED,
    AGENT_EXECUTION_STARTED,
)
from agents.factory.agent_state import is_disabled as is_agent_disabled
from tools.registry import ToolRegistry, get_tool_registry
from tools.runtime import ToolRuntime, get_tool_runtime


logger = logging.getLogger("neron.agent_runtime")


class AgentNotFoundError(LookupError):
    pass


class AgentToolUnavailableError(RuntimeError):
    pass


class AgentDisabledError(RuntimeError):
    """Agent présent mais désactivé (agents/factory/agent_state.py)."""


class AgentRuntime:
    def __init__(
        self,
        *,
        registry: DynamicAgentRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_runtime: ToolRuntime | None = None,
        store: AgentRuntimeStore | None = None,
        sandbox: AgentSandbox | None = None,
    ) -> None:
        self.registry = registry or DynamicAgentRegistry()
        self.tool_registry = tool_registry or get_tool_registry()
        self.tool_runtime = tool_runtime or (
            ToolRuntime(self.tool_registry)
            if tool_registry is not None
            else get_tool_runtime()
        )
        self.store = store or AgentRuntimeStore()
        self.sandbox = sandbox or AgentSandbox()
        self._loaded: dict[str, AgentInstance] = {}
        self._states: dict[str, dict[str, Any]] = {}

    def reload(self) -> dict[str, Any]:
        agents = self.registry.load_generated_agents()
        loaded_at = time.time()
        for name in agents:
            self._states.setdefault(
                name,
                {
                    "name": name,
                    "loaded_at": loaded_at,
                    "runs": 0,
                    "failures": 0,
                    "last_error": None,
                    "last_execution_ms": None,
                },
            )
        for name in set(self._states) - set(agents):
            self._states.pop(name, None)
        return {"ok": True, "count": len(agents), "agents": sorted(agents)}

    def list_agents(self) -> list[str]:
        return list(self.reload()["agents"])

    def get_state(self, name: str) -> dict[str, Any] | None:
        state = self._states.get(name)
        return dict(state) if state is not None else None

    def load_agent(self, agent_slug: str) -> AgentInstance:
        slug = str(agent_slug or "").strip()
        if not slug:
            raise AgentNotFoundError("agent_not_found:")

        agents = self.registry.load_generated_agents()
        resolved_slug = slug
        record = agents.get(slug)
        if record is None and not slug.endswith("_agent"):
            resolved_slug = f"{slug}_agent"
            record = agents.get(resolved_slug)
        if record is None:
            available = ",".join(sorted(agents))
            raise AgentNotFoundError(
                f"agent_not_found:{slug};available={available}"
            )

        generated_dir = getattr(self.registry, "generated_dir", None)
        if generated_dir is not None and is_agent_disabled(generated_dir, resolved_slug):
            raise AgentDisabledError(f"agent_disabled:{resolved_slug}")

        records = getattr(self.registry, "_records", {})
        record = records.get(resolved_slug, record) if isinstance(records, dict) else record
        spec = record.get("spec") if isinstance(record.get("spec"), dict) else {}

        instance = AgentInstance(
            agent_slug=resolved_slug,
            path=str(record.get("path") or ""),
            spec=spec,
            tools=self._bind_tools(spec),
        )
        self._loaded[resolved_slug] = instance
        return instance

    async def run_agent(
        self,
        agent_slug: str,
        request: str,
        context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentExecutionResult:
        started = time.monotonic()
        execution_context = ExecutionContext(
            request=str(request or ""),
            context=dict(context or {}),
            metadata=dict(metadata or {}),
        )
        result = AgentExecutionResult(
            execution_id=execution_context.execution_id,
            agent_slug=str(agent_slug or ""),
            status="running",
            started_at=utc_now_iso(),
        )
        self.store.save_execution(result, request=execution_context.request)
        self._log("agent_runtime_started", result, duration_ms=None)
        execution_started = False

        try:
            instance = self.load_agent(agent_slug)
            result.agent_slug = instance.agent_slug
            execution_context.tools = instance.tools
            event_bus.publish_background(Event(
                type=AGENT_EXECUTION_STARTED,
                source="agent_runtime",
                payload={
                    "execution_id": result.execution_id,
                    "agent_slug": result.agent_slug,
                    "request_metadata": execution_context.metadata,
                },
            ))
            execution_started = True
            sandbox_execution = await self._execute_agent(
                instance,
                execution_context,
            )
            sandbox_details = sandbox_execution.get("sandbox") or {}
            result.sandbox_used = True
            result.sandbox_backend = sandbox_details.get("backend_used")
            result.sandbox_isolation = (
                sandbox_details.get("isolation_level")
                or sandbox_details.get("isolation")
            )
            result.sudo_used = bool(sandbox_details.get("sudo_used"))
            if not sandbox_execution.get("ok"):
                sandbox_error = str(
                    sandbox_execution.get("error")
                    or "agent_sandbox_failed"
                )
                if sandbox_error.startswith("RuntimeError: "):
                    sandbox_error = sandbox_error.removeprefix(
                        "RuntimeError: "
                    )
                raise RuntimeError(
                    sandbox_error
                )
            raw = sandbox_execution.get("result")
            result.response, result.result = self._coerce_result(raw)
            result.result["sandbox"] = sandbox_details
            result.status = "completed"
        except Exception as exc:
            result.status = "failed"
            result.error = str(exc)

        result.finished_at = utc_now_iso()
        result.duration_ms = round((time.monotonic() - started) * 1000, 2)
        self.store.save_execution(result, request=execution_context.request)
        self._log(
            "agent_runtime_completed" if result.ok else "agent_runtime_failed",
            result,
            duration_ms=result.duration_ms,
        )
        if execution_started:
            event_bus.publish_background(Event(
                type=AGENT_EXECUTION_COMPLETED,
                source="agent_runtime",
                payload={
                    "execution_id": result.execution_id,
                    "agent_slug": result.agent_slug,
                    "status": result.status,
                    "duration_ms": result.duration_ms,
                    "error": result.error,
                },
            ))
        state = self._states.setdefault(
            result.agent_slug,
            {
                "name": result.agent_slug,
                "loaded_at": time.time(),
                "runs": 0,
                "failures": 0,
                "last_error": None,
                "last_execution_ms": None,
            },
        )
        state["runs"] += 1
        state["failures"] += 0 if result.ok else 1
        state["last_error"] = result.error
        state["last_execution_ms"] = result.duration_ms
        return result

    async def run(self, name: str, text: str = "") -> dict[str, Any]:
        result = await self.run_agent(name, text)
        payload = result.to_dict()
        if not result.ok:
            payload["available"] = self.list_agents()
        return payload

    def list_loaded_agents(self) -> list[str]:
        return sorted(self._loaded)

    def status(self) -> dict[str, Any]:
        return {
            "loaded_agents_count": len(self._loaded),
            "loaded_agents": self.list_loaded_agents(),
            "execution_count": self.store.count_executions(),
            "last_execution": self.store.last_execution(),
        }

    def _bind_tools(
        self,
        spec: dict[str, Any],
    ) -> dict[str, ToolBinding]:
        bindings: dict[str, ToolBinding] = {}
        missing: list[str] = []
        for slug in self._declared_tools(spec):
            tool_spec = self.tool_registry.get_tool(slug)
            if tool_spec is None:
                missing.append(slug)
            else:
                bindings[slug] = ToolBinding(
                    slug=slug,
                    spec=tool_spec,
                    runtime=self.tool_runtime,
                )
        if missing:
            raise AgentToolUnavailableError(
                f"agent_tool_unavailable:{','.join(sorted(missing))}"
            )
        return bindings

    def _declared_tools(
        self,
        spec: dict[str, Any],
    ) -> list[str]:
        declared: list[str] = []
        for value in (
            spec.get("tools"),
            spec.get("required_tools"),
        ):
            if isinstance(value, (list, tuple, set)):
                declared.extend(str(item) for item in value if str(item).strip())
        return list(dict.fromkeys(declared))

    async def _execute_agent(
        self,
        instance: AgentInstance,
        execution_context: ExecutionContext,
    ) -> dict[str, Any]:
        if not instance.path:
            return {"ok": False, "error": "agent_path_unavailable"}
        return await asyncio.to_thread(
            self.sandbox.execute_agent,
            instance.path,
            execution_context.request,
            context=execution_context.context,
            metadata=execution_context.metadata,
            tools=execution_context.tools,
            name=f"runtime_{instance.agent_slug}",
        )

    def _coerce_result(self, raw: Any) -> tuple[str, dict[str, Any]]:
        if isinstance(raw, dict):
            if raw.get("ok") is False or str(raw.get("status") or "").lower() in {
                "error",
                "failed",
            }:
                raise RuntimeError(str(raw.get("error") or "agent_execution_failed"))
            return str(raw.get("response") or raw.get("content") or ""), dict(raw)
        if hasattr(raw, "content"):
            if getattr(raw, "success", True) is False:
                raise RuntimeError(str(getattr(raw, "error", "agent_execution_failed")))
            return str(raw.content), {
                "content": raw.content,
                "success": getattr(raw, "success", True),
            }
        response = str(raw or "")
        return response, {"response": response}

    def _log(
        self,
        event: str,
        result: AgentExecutionResult,
        *,
        duration_ms: float | None,
    ) -> None:
        payload = {
            "event": event,
            "execution_id": result.execution_id,
            "agent_slug": result.agent_slug,
            "duration_ms": duration_ms,
            "status": result.status,
        }
        log = logger.error if event == "agent_runtime_failed" else logger.info
        log(json.dumps(payload, ensure_ascii=False, sort_keys=True))


_RUNTIME: AgentRuntime | None = None
_RUNTIME_LOCK = threading.Lock()


def get_agent_runtime() -> AgentRuntime:
    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is None:
            _RUNTIME = AgentRuntime()
        return _RUNTIME


def load_agent(agent_slug: str) -> AgentInstance:
    return get_agent_runtime().load_agent(agent_slug)


async def run_agent(
    agent_slug: str,
    request: str,
    context: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentExecutionResult:
    return await get_agent_runtime().run_agent(
        agent_slug,
        request,
        context=context,
        metadata=metadata,
    )
