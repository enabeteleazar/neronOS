from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

from agents.builtin.base_agent import get_logger
from modules.capabilities.models import CapabilityRequest
from core.pipeline.intent.intent_router import Intent, IntentResult, IntentRouter
from core.pipeline.routing.agent_router import AgentRouter
from core.modules.timer import detect_timer_intent, build_timer_response
from core.modules.identity import detect_identity_intent, build_identity_response
from core.modules.status import detect_status_intent, build_status_response
from core.modules.memory import detect_memory_intent, build_memory_response

logger = get_logger("core.pipeline.orchestrator")


@dataclass(frozen=True)
class OrchestratorDecision:
    intent: str
    selected_route: str
    reason: str
    complexity: str
    requires_llm: bool = False
    requires_timer: bool = False
    requires_memory: bool = False
    requires_tool: bool = False
    requires_resolver: bool = False
    requires_agent_factory: bool = False
    requires_goal_pipeline: bool = False
    requires_governor: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrchestratorResult:
    response: str
    intent: str
    confidence: float
    nlp: dict[str, Any]
    decision: OrchestratorDecision
    executor: str
    error: str | None = None
    model: str | None = None
    elapsed_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    multi_responses: list[str] = field(default_factory=list)
    fallback_used: bool = False
    retries: int = 0

    def to_metadata(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": _confidence_label(self.confidence),
            "nlp": self.nlp,
            "orchestrator_decision": self.decision.to_dict(),
            "selected_route": self.decision.selected_route,
            "executor": self.executor,
            "fallback_used": self.fallback_used,
            "retries": self.retries,
            "elapsed_ms": self.elapsed_ms,
            **self.metadata,
        }


class CoreOrchestrator:
    """Unique authority for user-facing routing in Neron Core."""

    def __init__(
        self,
        *,
        intent_router: IntentRouter | None = None,
        agent_router: AgentRouter | None = None,
        capability_resolver: Any | None = None,
        goal_orchestrator_factory: Any | None = None,
        goal_execution_engine: Any | None = None,
        goal_background_runner: Any | None = None,
        runtime_governor: Any | None = None,
    ) -> None:
        self.intent_router = intent_router or IntentRouter()
        self.agent_router = agent_router or AgentRouter()
        self._capability_resolver = capability_resolver
        self._goal_orchestrator_factory = goal_orchestrator_factory
        self._goal_execution_engine = goal_execution_engine
        self._goal_background_runner = goal_background_runner
        self._runtime_governor = runtime_governor

    async def decide(
        self,
        query: str,
        *,
        explicit_route: str | None = None,
    ) -> tuple[OrchestratorDecision, IntentResult]:
        intent_result = await self.intent_router.route(query)
        intent = intent_result.intent
        normalized = _normalize(query)
        complexity = _complexity(query)
        timer_result = detect_timer_intent(query)
        status_result = detect_status_intent(query)
        memory_result = detect_memory_intent(query)

        if explicit_route == "goal_pipeline" or normalized.startswith("/goal "):
            decision = OrchestratorDecision(
                intent="goal",
                selected_route="goal_pipeline",
                reason="Commande goal explicite recue par le Core.",
                complexity="complex",
                requires_goal_pipeline=True,
                requires_governor=True,
            )
        elif _is_timer_request(normalized):
            decision = OrchestratorDecision(
                intent="timer",
                selected_route="timer_engine",
                reason="Demande explicite de minuteur detectee.",
                complexity="simple",
                requires_timer=True,
            )
        elif status_result.get("matched"):
            decision = OrchestratorDecision(
                intent="status_query",
                selected_route="status_provider",
                reason="Demande d'état de Néron traitée localement par status_module.",
                complexity="simple",
                requires_llm=False,
                requires_timer=False,
                requires_memory=False,
                requires_tool=False,
                requires_resolver=False,
                requires_agent_factory=False,
                requires_goal_pipeline=False,
                requires_governor=False,
            )
        elif intent == Intent.IDENTITY_QUERY:
            decision = OrchestratorDecision(
                intent=Intent.IDENTITY_QUERY.value,
                selected_route="identity_provider",
                reason="Demande d'identité de Néron traitée localement depuis NERON.md.",
                complexity="simple",
                requires_llm=False,
                requires_timer=False,
                requires_memory=False,
                requires_tool=False,
                requires_resolver=False,
                requires_agent_factory=False,
                requires_goal_pipeline=False,
                requires_governor=False,
            )

        elif timer_result.get("matched") or intent == Intent.TIME_QUERY:
            decision = OrchestratorDecision(
                intent=Intent.TIME_QUERY.value,
                selected_route="timer_engine",
                reason="Demande de date ou heure detectee par timer_module.",
                complexity="simple",
                requires_timer=True,
            )
        elif memory_result.get("matched") or _is_memory_request(normalized):
            decision = OrchestratorDecision(
                intent="memory_query",
                selected_route="memory_engine",
                reason="Demande mémoire traitée localement par memory_module.",
                complexity="simple",
                requires_memory=True,
                requires_llm=False,
            )
        elif intent in {Intent.AGENT_CREATION, Intent.TOOL_CREATION}:
            decision = OrchestratorDecision(
                intent=intent.value,
                selected_route="agent_factory",
                reason="Creation explicite demandee; delegation au builder canonique.",
                complexity="complex",
                requires_agent_factory=True,
                requires_governor=True,
            )
        elif _is_agent_maintenance(normalized):
            decision = OrchestratorDecision(
                intent="agent_update",
                selected_route="tool_router",
                reason="Commande explicite de maintenance d'agent.",
                complexity=complexity,
                requires_tool=True,
                requires_governor=True,
            )
        elif _requires_specialized_resolution(normalized):
            decision = OrchestratorDecision(
                intent=intent.value,
                selected_route="resolver",
                reason="Demande complexe ou durable necessitant une capacite specialisee.",
                complexity="complex",
                requires_resolver=True,
                requires_governor=True,
            )
        elif (
            intent in _TOOL_INTENTS
            or _is_task_command(normalized)
        ):
            decision = OrchestratorDecision(
                intent=intent.value,
                selected_route="tool_router",
                reason="Une capacite deterministe existante correspond a l'intention.",
                complexity=complexity,
                requires_tool=True,
            )
        else:
            decision = OrchestratorDecision(
                intent=intent.value,
                selected_route="llm_provider",
                reason="Conversation ou explication generale sans moteur specialise requis.",
                complexity=complexity,
                requires_llm=True,
                requires_memory=True,
            )

        logger.info(
            json.dumps(
                {
                    "event": "orchestrator_decision",
                    **decision.to_dict(),
                    "confidence": intent_result.confidence_score,
                },
                ensure_ascii=False,
            )
        )
        logger.info(
            json.dumps(
                {
                    "event": "selected_route",
                    "selected_route": decision.selected_route,
                    "intent": decision.intent,
                    "reason": decision.reason,
                },
                ensure_ascii=False,
            )
        )
        return decision, intent_result

    async def handle(
        self,
        query: str,
        session_id: str = "default",
        *,
        source_channel: str = "api",
        user_id: str | None = None,
        request_metadata: dict[str, Any] | None = None,
        explicit_route: str | None = None,
    ) -> OrchestratorResult:
        del session_id
        started = time.monotonic()
        query = query.strip()
        decision, intent_result = await self.decide(
            query,
            explicit_route=explicit_route,
        )

        if decision.requires_governor:
            governor = self._get_runtime_governor()
            policy = governor.to_dict() if hasattr(governor, "to_dict") else {}
            self._log_used("governor_used", decision, policy=policy)

        try:
            response, executor, extra = await self._execute(
                decision,
                intent_result,
                query,
                source_channel=source_channel,
                user_id=user_id,
                request_metadata=request_metadata or {},
            )
            error = extra.pop("error", None)
            model = extra.pop("model", None)
            response_intent = str(extra.pop("resolved_intent", decision.intent))
        except Exception as exc:
            logger.exception(
                "orchestrator_execution_failed route=%s",
                decision.selected_route,
            )
            response = f"Erreur d'execution: {exc}"
            executor = decision.selected_route
            extra = {}
            error = str(exc)
            model = None
            response_intent = decision.intent

        return OrchestratorResult(
            response=response,
            intent=response_intent,
            confidence=intent_result.confidence_score,
            nlp=intent_result.to_nlp_dict(),
            decision=decision,
            executor=executor,
            error=error,
            model=model,
            elapsed_ms=round((time.monotonic() - started) * 1000, 2),
            metadata=extra,
        )

    async def run_goal(
        self,
        objective: str,
        *,
        source: str = "api",
    ) -> dict[str, Any]:
        decision, _ = await self.decide(
            objective,
            explicit_route="goal_pipeline",
        )
        if decision.requires_governor:
            self._log_used("governor_used", decision)
        self._log_used("goal_pipeline_used", decision)
        self._log_used("planner_used", decision, usage="planning_only")
        return await self._get_goal_orchestrator().run_goal(
            objective.strip(),
            source=source,
        )

    async def queue_goal(
        self,
        objective: str,
        *,
        source: str = "api",
    ) -> dict[str, Any]:
        decision, _ = await self.decide(
            objective,
            explicit_route="goal_pipeline",
        )
        if decision.requires_governor:
            self._log_used("governor_used", decision)
        self._log_used("goal_pipeline_used", decision)
        self._log_used("planner_used", decision, usage="planning_only")

        orchestrator = self._get_goal_orchestrator()
        goal = orchestrator.queue_goal(objective.strip(), source=source)
        goal_id = str(goal["id"])

        execution_engine = self._get_goal_execution_engine()
        background_runner = self._get_goal_background_runner()
        execution_engine.enqueue_goal(
            goal_id,
            objective.strip(),
            source,
            dict(goal.get("metadata") or {}),
        )
        background_runner.submit(
            goal_id=goal_id,
            objective=objective.strip(),
            source=source,
        )
        return goal

    async def _execute(
        self,
        decision: OrchestratorDecision,
        intent_result: IntentResult,
        query: str,
        *,
        source_channel: str,
        user_id: str | None,
        request_metadata: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any]]:
        route = decision.selected_route

        if route == "timer_engine":
            self._log_used("timer_used", decision)
            return self._execute_timer(query, decision)

        if route == "status_provider":
            self._log_used("status_used", decision)
            return self._execute_status(query, decision)

        if route == "identity_provider":
            self._log_used("identity_used", decision)
            return self._execute_identity(query, decision)

        if route == "memory_engine":
            self._log_used("memory_used", decision)
            return await self._execute_memory(query)

        if route == "resolver":
            self._log_used("resolver_used", decision)
            request = CapabilityRequest(
                text=query,
                source="user",
                channel=source_channel,
                user_id=user_id,
                metadata=request_metadata,
            )
            result = await self._get_capability_resolver().resolve(request)
            if result is not None:
                if result.async_started or result.goal_id:
                    self._log_used(
                        "goal_pipeline_used",
                        decision,
                        delegated_by="resolver",
                    )
                selected = (
                    result.tool_slug
                    or result.agent_slug
                    or (
                        result.decision.decision
                        if result.decision is not None
                        else "capability_resolver"
                    )
                )
                return (
                    result.response,
                    str(selected),
                    {
                        "capability": result.to_dict(),
                        "error": result.error,
                        "resolved_intent": (
                            result.decision.decision
                            if result.decision is not None
                            else decision.intent
                        ),
                    },
                )
            fallback = OrchestratorDecision(
                intent=decision.intent,
                selected_route="llm_provider",
                reason="Resolver sans resultat; fallback decide par l'Orchestrator.",
                complexity=decision.complexity,
                requires_llm=True,
                requires_memory=True,
            )
            self._log_used("llm_provider_used", fallback)
            response = await self.agent_router.route(intent_result, query)
            return response, "llm_agent", {"resolver_fallback": True}

        if route == "goal_pipeline":
            self._log_used("goal_pipeline_used", decision)
            self._log_used("planner_used", decision, usage="planning_only")
            objective = re.sub(r"^\s*/goal\s+", "", query, flags=re.IGNORECASE)
            result = await self._get_goal_orchestrator().run_goal(
                objective,
                source=source_channel,
            )
            return _goal_response_text(result), "goal_pipeline", {"goal": result}

        if route == "agent_factory":
            self._log_used("agent_factory_used", decision)
            response = await self.agent_router.route(
                intent_result,
                query,
                source_channel=source_channel,
            )
            return response, "agent_build_orchestrator", {}

        if route == "tool_router":
            self._log_used("tool_router_used", decision)
            response = await self.agent_router.route(
                intent_result,
                query,
                source_channel=source_channel,
            )
            if decision.intent == "agent_update":
                return response, "agent_manager", {
                    "resolved_intent": "agent_update",
                    "routed_before_llm": True,
                }
            return response, _executor_for_intent(intent_result.intent), {}

        self._log_used("llm_provider_used", decision)
        if decision.requires_memory:
            self._log_used("memory_used", decision, usage="context")
        response = await self.agent_router.route(
            intent_result,
            query,
            source_channel=source_channel,
        )
        return response, "llm_agent", {}

    def _execute_status(
        self,
        query: str,
        decision: OrchestratorDecision,
    ) -> tuple[str, str, dict[str, Any]]:
        status_result = detect_status_intent(query)
        kind = status_result.get("kind") or "core_status"
        result = build_status_response(kind)

        metadata = {
            "selected_route": "status_provider",
            "executor": "status_module",
            "fallback_used": False,
            "retries": 0,
            "source": result.get("source"),
            "status_kind": kind,
            "status_confidence": status_result.get("confidence"),
            "status": result.get("status"),
        }

        return result["response"], result["agent"], metadata

    def _execute_identity(
        self,
        query: str,
        decision: OrchestratorDecision,
    ) -> tuple[str, str, dict[str, Any]]:
        identity_result = detect_identity_intent(query)
        status_result = detect_status_intent(query)
        kind = identity_result.get("kind") or "identity"
        result = build_identity_response(kind)

        metadata = {
            "selected_route": "identity_provider",
            "executor": "identity_module",
            "fallback_used": False,
            "retries": 0,
            "source": result.get("source"),
            "identity_kind": kind,
            "identity_confidence": identity_result.get("confidence"),
        }

        return result["response"], result["agent"], metadata

    def _execute_timer(
        self,
        query: str,
        decision: OrchestratorDecision,
    ) -> tuple[str, str, dict[str, Any]]:
        timer_result = detect_timer_intent(query)
        kind = timer_result.get("kind") or "datetime"
        result = build_timer_response(kind)

        metadata = {
            "selected_route": "timer_engine",
            "executor": "timer_module",
            "fallback_used": False,
            "retries": 0,
            "iso": result.get("iso"),
            "source": "timer_module",
            "timer_kind": kind,
            "timer_confidence": timer_result.get("confidence"),
        }

        return result["response"], result["agent"], metadata

    async def _execute_memory(
        self,
        query: str,
    ) -> tuple[str, str, dict[str, Any]]:
        memory_result = detect_memory_intent(query)
        kind = memory_result.get("kind") or "recall"
        result = build_memory_response(kind, query)

        metadata = {
            "selected_route": "memory_engine",
            "executor": "memory_module",
            "fallback_used": False,
            "retries": 0,
            "source": result.get("source"),
            "memory_kind": kind,
            "memory_confidence": memory_result.get("confidence"),
        }

        if "memory" in result:
            metadata["memory"] = result["memory"]

        if "memories" in result:
            metadata["memories"] = result["memories"]

        return result["response"], result["agent"], metadata


    def _get_capability_resolver(self) -> Any:
        if self._capability_resolver is None:
            from modules.capabilities.resolver import CapabilityResolver

            self._capability_resolver = CapabilityResolver()
        return self._capability_resolver

    def _get_goal_orchestrator(self) -> Any:
        if self._goal_orchestrator_factory is None:
            from goal.goals.goal_orchestrator import get_goal_orchestrator

            self._goal_orchestrator_factory = get_goal_orchestrator
        return self._goal_orchestrator_factory()

    def _get_runtime_governor(self) -> Any:
        if self._runtime_governor is None:
            from core.runtime.governor import get_runtime_governor

            self._runtime_governor = get_runtime_governor()
        return self._runtime_governor

    def _get_goal_execution_engine(self) -> Any:
        if self._goal_execution_engine is None:
            from goal.goals.execution_engine import get_goal_execution_engine

            self._goal_execution_engine = get_goal_execution_engine()
        return self._goal_execution_engine

    def _get_goal_background_runner(self) -> Any:
        if self._goal_background_runner is None:
            from goal.goals.background_runner import get_goal_background_runner

            self._goal_background_runner = get_goal_background_runner()
        return self._goal_background_runner

    @staticmethod
    def _log_used(
        event: str,
        decision: OrchestratorDecision,
        **metadata: Any,
    ) -> None:
        logger.info(
            json.dumps(
                {
                    "event": event,
                    "selected_route": decision.selected_route,
                    "intent": decision.intent,
                    **metadata,
                },
                ensure_ascii=False,
            )
        )


# Historical name retained for compatibility.
NLPOrchestrator = CoreOrchestrator

_core_orchestrator: CoreOrchestrator | None = None


def get_core_orchestrator() -> CoreOrchestrator:
    global _core_orchestrator
    if _core_orchestrator is None:
        _core_orchestrator = CoreOrchestrator()
    return _core_orchestrator


def set_core_orchestrator(orchestrator: CoreOrchestrator | None) -> None:
    global _core_orchestrator
    _core_orchestrator = orchestrator


_TOOL_INTENTS = {
    Intent.WEB_SEARCH,
    Intent.HA_ACTION,
    Intent.CODE,
    Intent.CODE_AUDIT,
    Intent.SYSTEM_STATUS,
    Intent.NETWORK_STATUS,
    Intent.SELF_STATUS,
    Intent.NEWS_QUERY,
    Intent.WEATHER_QUERY,
    Intent.TODO_ACTION,
    Intent.WIKI_QUERY,
    Intent.PERSONALITY_FEEDBACK,
    Intent.AGENT_LIST,
    Intent.AGENT_RUN,
    Intent.PROJECT_STATUS,
    Intent.PROJECT_LIST,
}


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    normalized = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    return " ".join(
        normalized.replace("'", " ").replace("’", " ").replace("-", " ").split()
    )


def _complexity(query: str) -> str:
    words = len(query.split())
    if words >= 35 or query.count("\n") >= 3:
        return "complex"
    if words >= 12:
        return "medium"
    return "simple"


def _is_timer_request(query: str) -> bool:
    return any(token in query for token in ("minuteur", "timer", "compte a rebours"))


def _is_date_request(query: str) -> bool:
    return any(
        token in query
        for token in (
            "quelle date",
            "quel jour",
            "on est le combien",
            "date sommes",
        )
    )


def _is_memory_request(query: str) -> bool:
    return any(
        token in query
        for token in (
            "souviens toi",
            "memorise",
            "retiens",
            "retient",
            "note ceci",
            "cherche dans la memoire",
            "recherche memoire",
            "retrouve mes notes",
        )
    )


def _requires_specialized_resolution(query: str) -> bool:
    durable = (
        "automatiquement",
        "en continu",
        "periodiquement",
        "surveille",
        "alerte moi",
        "previens moi",
    )
    complex_request = (
        "analyse cette demande complexe",
        "capacite specialisee",
        "paques",
        "sous reseau",
        "subnet",
    )
    return any(token in query for token in durable + complex_request)


def _is_task_command(query: str) -> bool:
    return any(
        token in query
        for token in (
            "etat des taches",
            "status des taches",
            "prochaine tache",
            "lance la prochaine tache",
        )
    )


def _is_agent_maintenance(query: str) -> bool:
    return any(
        query.startswith(token)
        for token in (
            "mets a jour ",
            "met a jour ",
            "ameliore agent ",
            "update agent ",
            "scan agents",
            "rescanner agents",
            "index agents",
            "agents invalides",
            "valide agent ",
            "valide l agent ",
            "promeut agent ",
            "active agent ",
        )
    )


def _timer_seconds(query: str) -> int | None:
    normalized = _normalize(query)
    match = re.search(
        r"(\d+)\s*(seconde|secondes|minute|minutes|heure|heures)",
        normalized,
    )
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    if unit.startswith("heure"):
        return value * 3600
    if unit.startswith("minute"):
        return value * 60
    return value


def _human_duration(seconds: int) -> str:
    if seconds % 3600 == 0:
        return f"{seconds // 3600} heure(s)"
    if seconds % 60 == 0:
        return f"{seconds // 60} minute(s)"
    return f"{seconds} seconde(s)"


def _confidence_label(score: float) -> str:
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def _executor_for_intent(intent: Intent) -> str:
    return {
        Intent.WEB_SEARCH: "web_agent",
        Intent.HA_ACTION: "ha_agent",
        Intent.CODE: "code_agent",
        Intent.CODE_AUDIT: "code_audit_agent",
        Intent.SYSTEM_STATUS: "system_agent",
        Intent.NETWORK_STATUS: "system_agent",
        Intent.SELF_STATUS: "self_model",
        Intent.NEWS_QUERY: "news_agent",
        Intent.WEATHER_QUERY: "weather_agent",
        Intent.TODO_ACTION: "todo_agent",
        Intent.WIKI_QUERY: "wiki_agent",
        Intent.PERSONALITY_FEEDBACK: "personality",
        Intent.AGENT_LIST: "agent_registry",
        Intent.AGENT_RUN: "agent_runtime",
        Intent.PROJECT_STATUS: "project_manager",
        Intent.PROJECT_LIST: "project_manager",
    }.get(intent, "tool_router")


def _goal_response_text(result: dict[str, Any]) -> str:
    response = result.get("response") or result.get("message")
    if response:
        return str(response)
    status = result.get("status") or "unknown"
    plan = result.get("plan") or {}
    plan_id = str(plan.get("id") or "")
    suffix = f" Plan: {plan_id[:8]}." if plan_id else ""
    return f"Objectif traite. Statut: {status}.{suffix}"
