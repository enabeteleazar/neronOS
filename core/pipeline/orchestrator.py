from __future__ import annotations

import asyncio
import json
import re
import shlex
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from core.agent_registry import get_logger
from modules.capabilities.models import CapabilityRequest
from core.constants import NERON_HELP_TEXT
from core.pipeline.intent.intent_router import Intent, IntentResult, IntentRouter
from core.pipeline.nlp.french_normalizer import normalize_text
from core.pipeline.routing.agent_router import AgentRouter
from core.modules.timer import detect_timer_intent, build_timer_response
from core.modules.identity import (
    build_identity_response_async,
    detect_identity_intent,
)
from core.modules.status import (
    build_status_response_async,
    detect_status_intent,
)
from core.modules.memory import detect_memory_intent, build_memory_response_async
from core.modules.knowledge import build_knowledge_response_async, detect_knowledge_intent
from core.infrastructure.registry import service_registry
from core.infrastructure.topology import build_topology
from core.providers.models import ProviderRequest
from core.providers.registry import provider_registry

logger = get_logger("core.pipeline.orchestrator")

# Le Core (Agent Patron) ne traite pas les objectifs de chantier : ils relèvent
# du Manager de chantier. Aucune interface de délégation n'est définie à ce jour.
# Civilites : reponses locales, sans modele de langage. La cascade de mots-cles
# reconnaissait deja ces intents, mais aucune branche ne les traitait — ils
# finissaient sur le provider LLM, soit 67 s pour repondre « Bonjour »
# (mesure du 03/09/2026). Reponses volontairement sobres et stables : ce sont
# des accuses de reception, pas des reponses a construire.
# Correction initiale : 80d6794, perdue lors de la reintegration du Core
# (58ab382), retablie ici. Voir tests/test_smalltalk_stays_local.py.
_SMALLTALK_REPLIES: dict[Intent, str] = {
    Intent.GREETING: "Bonjour. Que puis-je faire pour toi ?",
    Intent.THANKS: "Je t'en prie.",
    Intent.GOODBYE: "À bientôt.",
    Intent.STATUS_SMALLTALK: "Tout va bien, merci. Et toi ?",
}

MANAGER_DELEGATION_ROUTE = "manager_delegation"
MANAGER_DELEGATION_MESSAGE = (
    "Cette demande relève du Manager de chantier (objectifs, plans, tâches, "
    "création d'agents). Le Core ne l'exécute pas : aucune délégation n'est "
    "encore configurée."
)


@dataclass(frozen=True)
class OrchestratorDecision:
    intent: str
    selected_route: str
    reason: str
    complexity: str
    requires_llm: bool = False
    requires_timer: bool = False
    requires_memory: bool = False
    requires_knowledge: bool = False
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
        runtime_governor: Any | None = None,
        agent_runtime_factory: Any | None = None,
    ) -> None:
        self.intent_router = intent_router or IntentRouter()
        self.agent_router = agent_router or AgentRouter()
        self._capability_resolver = capability_resolver
        self._runtime_governor = runtime_governor
        self._agent_runtime_factory = agent_runtime_factory

    async def decide(
        self,
        query: str,
        *,
        explicit_route: str | None = None,
    ) -> tuple[OrchestratorDecision, IntentResult]:
        routing_query = _normalize(query)
        intent_result = await self.intent_router.route(routing_query, raw_query=query)
        intent = intent_result.intent
        normalized = routing_query
        complexity = _complexity(query)
        timer_result = detect_timer_intent(routing_query)
        status_result = detect_status_intent(routing_query)
        memory_result = detect_memory_intent(routing_query)
        knowledge_result = detect_knowledge_intent(routing_query)
        gateway_domain = _detect_gateway_domain(routing_query)
        pc_remote_match = _detect_pc_remote_action(routing_query)
        agent_admin = _parse_agent_admin(query)
        agent_invocation = _parse_agent_invocation(query)

        if normalized == "/help":
            decision = OrchestratorDecision(
                intent="help",
                selected_route="help_provider",
                reason="Commande d'aide explicite traitée localement par le Core.",
                complexity="simple",
            )
        elif explicit_route == "goal_pipeline" or normalized.startswith("/goal "):
            decision = OrchestratorDecision(
                intent="goal",
                selected_route=MANAGER_DELEGATION_ROUTE,
                reason="Commande goal explicite : hors périmètre du Core, relève du Manager de chantier.",
                complexity="complex",
                requires_goal_pipeline=True,
                requires_governor=True,
            )
        elif agent_admin is not None:
            decision = OrchestratorDecision(
                intent=_AGENT_ADMIN_INTENTS[agent_admin[0]].value,
                selected_route="agent_admin",
                reason="Gestion d'un agent (activation, désactivation, suppression) déléguée à Goal en HTTP.",
                complexity="simple",
            )
        elif agent_invocation is not None:
            decision = OrchestratorDecision(
                intent="agent_invocation",
                selected_route="registered_agent_runtime",
                reason="Invocation explicite d'un agent enregistré traitée par le Runtime.",
                complexity="simple",
            )
        elif _is_agent_maintenance(normalized):
            decision = OrchestratorDecision(
                intent="agent_update",
                selected_route="agent_manager",
                reason="Commande de maintenance agent détectée avant le routage timer.",
                complexity="medium",
                requires_agent_factory=True,
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
        elif _is_self_model_request(normalized):
            decision = OrchestratorDecision(
                intent=Intent.SELF_STATUS.value,
                selected_route="tool_router",
                reason="Demande de modèle interne traitée par le SelfModel local.",
                complexity="simple",
                requires_tool=True,
            )
        elif intent == Intent.REGISTRY_LIST:
            decision = OrchestratorDecision(
                intent=Intent.REGISTRY_LIST.value,
                selected_route="registry_provider",
                reason="Demande de liste des services traitée localement par le registre.",
                complexity="simple",
                requires_llm=False,
                requires_timer=False,
                requires_memory=False,
                requires_tool=False,
                requires_resolver=False,
                requires_goal_pipeline=False,
                requires_governor=False,
            )
        elif intent == Intent.REGISTRY_STATUS:
            decision = OrchestratorDecision(
                intent=Intent.REGISTRY_STATUS.value,
                selected_route="registry_provider",
                reason="Demande d'etat des services (arrets/en cours) traitee localement par le registre.",
                complexity="simple",
                requires_llm=False,
                requires_timer=False,
                requires_memory=False,
                requires_tool=False,
                requires_resolver=False,
                requires_goal_pipeline=False,
                requires_governor=False,
            )
        elif intent == Intent.TOPOLOGY_SHOW:
            decision = OrchestratorDecision(
                intent=Intent.TOPOLOGY_SHOW.value,
                selected_route="topology_provider",
                reason="Demande de topologie du systeme traitee localement par le module de topologie.",
                complexity="simple",
                requires_llm=False,
                requires_timer=False,
                requires_memory=False,
                requires_tool=False,
                requires_resolver=False,
                requires_goal_pipeline=False,
                requires_governor=False,
            )
        elif intent == Intent.MEMORY_SEARCH:
            decision = OrchestratorDecision(
                intent=Intent.MEMORY_SEARCH.value,
                selected_route="memory_provider",
                reason="Recherche mémoire traitée via le Provider Registry.",
                complexity="simple",
                requires_llm=False,
                requires_timer=False,
                requires_memory=True,
                requires_tool=False,
                requires_resolver=False,
                requires_agent_factory=False,
                requires_goal_pipeline=False,
                requires_governor=False,
            )
        elif intent in {Intent.AGENT_CREATION, Intent.TOOL_CREATION}:
            decision = OrchestratorDecision(
                intent=intent.value,
                selected_route=MANAGER_DELEGATION_ROUTE,
                reason="Création d'agent ou d'outil : hors périmètre du Core, relève du Manager de chantier.",
                complexity="complex",
                requires_goal_pipeline=True,
                requires_governor=True,
            )
        elif _is_goal_engine_request(normalized):
            decision = OrchestratorDecision(
                intent="goal_execution",
                selected_route=MANAGER_DELEGATION_ROUTE,
                reason="Exécution par agent de chantier : hors périmètre du Core, relève du Manager de chantier.",
                complexity="complex",
                requires_goal_pipeline=True,
                requires_governor=True,
            )
        elif intent in _SMALLTALK_REPLIES:
            # Placee AVANT la branche status : « comment vas-tu » et « ca va »
            # sont captes par `detect_status_intent` comme `health_query`, et
            # recevaient donc un rapport technique la ou la cascade de
            # mots-cles les avait — correctement — classes en
            # `status_smalltalk`, c'est-a-dire en civilite. Une demande d'etat
            # explicite (« quel est ton statut ») porte un autre intent et
            # continue de passer par status_provider.
            decision = OrchestratorDecision(
                intent=intent.value,
                selected_route="smalltalk",
                reason="Civilite traitee localement par le Core.",
                complexity="simple",
            )
        elif gateway_domain is not None:
            # Doit primer sur status_provider ci-dessous : le classifieur
            # d'intent confond « montre mes contacts/mails/rappels » avec une
            # requete d'etat systeme (intent=system_status). Le domaine
            # externe, detecte de facon deterministe, est prioritaire.
            # Correction initiale : 78a93ea (26/09/2026), perdue lors de la
            # reintegration du Core (58ab382), retablie ici.
            decision = OrchestratorDecision(
                intent=intent.value,
                selected_route="resolver",
                reason=(
                    f"Domaine externe '{gateway_domain}' porte par le "
                    "registre de passerelles (server/gateways)."
                ),
                complexity="complex",
                requires_resolver=True,
                requires_governor=True,
            )
        elif pc_remote_match:
            # Même motif que gateway_domain juste au-dessus : le classifieur
            # confond ces phrases avec system_status (« ouvre »/« ferme »/« pc »
            # pris pour restart_service/backup). Sans priorité ici, elles sont
            # captées par status_provider avant d'atteindre _TOOL_INTENTS.
            # Constaté le 27/09/2026 : « ouvre htop sur mon pc distant » ->
            # system_status. Rétabli : 48ba388, perdu avec 58ab382.
            intent_result.intent = Intent.PC_REMOTE
            decision = OrchestratorDecision(
                intent=Intent.PC_REMOTE.value,
                selected_route="tool_router",
                reason="Commande de contrôle PC distant (pc_remote) détectée de façon déterministe.",
                complexity="simple",
                requires_tool=True,
            )
        elif (
            status_result.get("matched") or intent == Intent.SYSTEM_STATUS
        ) and not memory_result.get("matched"):
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
        elif (
            intent == Intent.IDENTITY_QUERY
            and not memory_result.get("matched")
        ):
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
        elif intent == Intent.SELF_STATUS:
            decision = OrchestratorDecision(
                intent=Intent.SELF_STATUS.value,
                selected_route="tool_router",
                reason="Demande de modèle interne traitée par le SelfModel local.",
                complexity="simple",
                requires_tool=True,
            )
        elif memory_result.get("matched") or _is_memory_request(normalized):
            kind = memory_result.get("kind") or "recall"
            decision = OrchestratorDecision(
                intent=f"memory_{kind}",
                selected_route="memory_provider",
                reason="Demande mémoire traitée via le Provider Registry.",
                complexity="simple",
                requires_memory=True,
                requires_llm=False,
            )
        elif knowledge_result.get("matched"):
            kind = knowledge_result.get("kind") or "query"
            decision = OrchestratorDecision(
                intent=f"knowledge_{kind}",
                selected_route="knowledge_provider",
                reason="Demande de consultation de documentation traitée via le Provider Registry.",
                complexity="simple",
                requires_knowledge=True,
                requires_llm=False,
            )
        elif _requires_goal_pipeline(normalized):
            decision = OrchestratorDecision(
                intent=intent.value,
                selected_route=MANAGER_DELEGATION_ROUTE,
                reason="Objectif d'exécution structurée : hors périmètre du Core, relève du Manager de chantier.",
                complexity="complex",
                requires_goal_pipeline=True,
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
                    "normalized_query": routing_query,
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
        normalized_query = _normalize(query)
        decision, intent_result = await self.decide(
            query,
            explicit_route=explicit_route,
        )

        # UNE seule chaîne de mémorisation par message, après le routage
        # (cde7ea0 + correction du 08/09, perdus avec 58ab382). En tâche de
        # fond : le juge LLM de memory peut prendre des dizaines de secondes,
        # la réponse à l'utilisateur ne l'attend pas.
        if query and _message_a_observer(decision):
            self._schedule_observe(query)

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
            model = extra.get("model")
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

        logger.info(
            json.dumps(
                {
                    "event": "orchestrator_execution",
                    "intent": decision.intent,
                    "selected_route": decision.selected_route,
                    "reason": decision.reason,
                    "executor": executor,
                    "requires_llm": decision.requires_llm,
                },
                ensure_ascii=False,
            )
        )

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
            metadata={
                **extra,
                "normalized_query": normalized_query,
            },
        )

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

        if route == "help_provider":
            self._log_used("help_used", decision)
            return NERON_HELP_TEXT, "help_provider", {}

        if route == "registered_agent_runtime":
            self._log_used("registered_agent_runtime_used", decision)
            return await self._execute_registered_agent(query, request_metadata)

        if route == "smalltalk":
            self._log_used("smalltalk_used", decision)
            return self._execute_smalltalk(decision)

        if route == "timer_engine":
            self._log_used("timer_used", decision)
            return self._execute_timer(query, decision)

        if route == "status_provider":
            self._log_used("status_used", decision)
            return await self._execute_status(query, decision)

        if route == "identity_provider":
            self._log_used("identity_used", decision)
            return await self._execute_identity(query, decision)

        if route == "memory_provider":
            self._log_used("memory_provider_used", decision)
            return await self._execute_memory_provider(query, decision)

        if route == "knowledge_provider":
            self._log_used("knowledge_provider_used", decision)
            return await self._execute_knowledge_provider(query, decision)

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
            response, executor, metadata = await self._execute_llm_provider(
                query,
                fallback,
            )
            return response, executor, {**metadata, "resolver_fallback": True}

        if route == MANAGER_DELEGATION_ROUTE:
            self._log_used("manager_delegation_refused", decision)
            return (
                MANAGER_DELEGATION_MESSAGE,
                MANAGER_DELEGATION_ROUTE,
                {"delegated": False, "owner": "manager_de_chantier"},
            )

        if route == "agent_factory":
            self._log_used("agent_factory_used", decision)
            response = await self.agent_router.route(
                intent_result,
                query,
                source_channel=source_channel,
            )
            return response, "agent_build_orchestrator", {}

        if route == "agent_admin":
            self._log_used("agent_admin_used", decision)
            return await self._execute_agent_admin(query)

        if route == "agent_manager":
            self._log_used("agent_manager_used", decision)
            response = await self.agent_router.route(
                intent_result,
                query,
                source_channel=source_channel,
            )
            return response, "agent_manager", {
                "resolved_intent": "agent_update",
                "routed_before_llm": True,
            }

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
        if route == "registry_provider":
            self._log_used("registry_used", decision)
            return await self._execute_registry(query, decision)

        if route == "topology_provider":
            self._log_used("topology_used", decision)
            return await self._execute_topology(query, decision)

        if route == "llm_provider":
            self._log_used("llm_provider_used", decision)
            return await self._execute_llm_provider(query, decision)

        self._log_used("llm_provider_used", decision)
        return await self._execute_llm_provider(query, decision)

    async def _execute_status(
        self,
        query: str,
        decision: OrchestratorDecision,
    ) -> tuple[str, str, dict[str, Any]]:
        status_result = detect_status_intent(query)
        kind = status_result.get("kind") or "core_status"
        result = await build_status_response_async(
            kind,
            question=query,
            use_llm=False,
        )
        normalized_kind = result.get("status_kind") or kind

        metadata = {
            "selected_route": "status_provider",
            "executor": "status_module",
            "fallback_used": False,
            "retries": 0,
            "source": result.get("source"),
            "status_kind": normalized_kind,
            "status_confidence": status_result.get("confidence"),
            "status_llm_used": result.get("llm_used", False),
            "status": result.get("status"),
        }

        return result["response"], result["agent"], metadata

    async def _execute_registered_agent(
        self,
        query: str,
        request_metadata: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any]]:
        invocation = _parse_agent_invocation(query)
        if invocation is None:
            error = "Commande d’invocation agent invalide."
            return error, "agent_runtime", {
                "error": error,
                "invoked_agent": None,
                "registry_lookup": "not_found",
                "runtime_status": "not_started",
                "sandbox_used": False,
            }

        runtime = self._get_agent_runtime()
        registry_status = runtime.reload()
        available = set(registry_status.get("agents") or [])
        resolved_slug = invocation.agent_slug
        if resolved_slug not in available and not resolved_slug.endswith("_agent"):
            candidate = f"{resolved_slug}_agent"
            if candidate in available:
                resolved_slug = candidate

        if resolved_slug not in available:
            error = f"Agent introuvable : {invocation.agent_slug}"
            return error, "agent_runtime", {
                "error": error,
                "invoked_agent": invocation.agent_slug,
                "registry_lookup": "not_found",
                "runtime_status": "not_started",
                "sandbox_used": False,
            }

        execution = await runtime.run_agent(
            resolved_slug,
            invocation.agent_input,
            metadata={
                **request_metadata,
                "invocation_source": "core_orchestrator",
                "original_query": query,
            },
        )
        metadata = {
            "invoked_agent": execution.agent_slug or resolved_slug,
            "registry_lookup": "found",
            "runtime_status": execution.status,
            "sandbox_used": bool(getattr(execution, "sandbox_used", False)),
            "sandbox_backend": getattr(execution, "sandbox_backend", None),
            "sandbox_isolation": getattr(execution, "sandbox_isolation", None),
            "sudo_used": bool(getattr(execution, "sudo_used", False)),
            "runtime_execution": execution.to_dict(),
        }
        if not execution.ok:
            error = execution.error or "agent_execution_failed"
            return (
                f"Erreur agent {resolved_slug} : {error}",
                "agent_runtime",
                {**metadata, "error": error},
            )
        return execution.response, "agent_runtime", {**metadata, "error": None}

    async def _execute_identity(
        self,
        query: str,
        decision: OrchestratorDecision,
    ) -> tuple[str, str, dict[str, Any]]:
        identity_result = detect_identity_intent(query)
        kind = identity_result.get("kind") or "identity"
        result = await build_identity_response_async(
            kind,
            question=query,
            use_llm=False,
        )

        metadata = {
            "selected_route": "identity_provider",
            "executor": "identity_module",
            "fallback_used": False,
            "retries": 0,
            "source": result.get("source"),
            "identity_source": result.get("source"),
            "identity_kind": kind,
            "identity_confidence": identity_result.get("confidence"),
            "identity_llm_used": result.get("llm_used", False),
        }

        return result["response"], result["agent"], metadata

    def _execute_smalltalk(
        self,
        decision: OrchestratorDecision,
    ) -> tuple[str, str, dict[str, Any]]:
        """Civilites : reponse locale immediate, aucun appel sortant."""
        try:
            intent = Intent(decision.intent)
        except ValueError:
            intent = Intent.GREETING

        response = _SMALLTALK_REPLIES.get(intent, _SMALLTALK_REPLIES[Intent.GREETING])

        metadata = {
            "selected_route": "smalltalk",
            "executor": "smalltalk_module",
            "fallback_used": False,
            "retries": 0,
            "source": "smalltalk_module",
            "llm_used": False,
        }

        return response, "smalltalk_module", metadata

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
        result = await build_memory_response_async(kind, query)

        metadata = {
            "selected_route": "memory_engine",
            "executor": "memory_module",
            "fallback_used": False,
            "retries": 0,
            "source": result.get("source"),
            "memory_kind": kind,
            "memory_response_mode": result.get("memory_response_mode"),
            "memory_confidence": memory_result.get("confidence"),
            "memory_llm_used": result.get("memory_llm_used", False),
        }

        if "memory" in result:
            metadata["memory"] = result["memory"]

        if "memories" in result:
            metadata["memories"] = result["memories"]

        if "oblivia_memories" in result:
            metadata["oblivia_memories"] = result["oblivia_memories"]

        return result["response"], result["agent"], metadata

    async def _execute_memory_provider(
        self,
        query: str,
        decision: OrchestratorDecision,
    ) -> tuple[str, str, dict[str, Any]]:
        memory_result = detect_memory_intent(query)
        action = _memory_provider_action(query, memory_result, decision)
        memory_query = (
            _extract_memory_search_query(query)
            if action == "search"
            else _extract_memory_recall_query(query)
        )
        remembered_content = _extract_memory_remember_content(query)
        providers = provider_registry.by_type("memory")
        provider_info = providers[0] if providers else None
        provider = provider_registry.get(provider_info.name) if provider_info else None

        metadata = {
            "selected_route": "memory_provider",
            "executor": provider_info.name if provider_info else "memory_provider",
            "fallback_used": False,
            "retries": 0,
            "memory_action": action,
            "memory_query": memory_query if action in {"search", "recall"} else None,
            "memory_results_count": 0,
            "llm_used": False,
            "resolved_intent": (
                Intent.MEMORY_SEARCH.value if action == "search" else f"memory_{action}"
            ),
        }

        if provider is None:
            return (
                "Le provider mémoire n'est pas disponible.",
                "memory_provider",
                {**metadata, "error": "memory provider unavailable"},
            )

        payload: dict[str, Any]
        if action == "remember":
            payload = {
                "content": remembered_content,
                "category": "unknown",
                "metadata": {"source": "core_orchestrator"},
            }
        elif action == "recall":
            payload = {"query": memory_query, "limit": 5}
        else:
            payload = {"query": memory_query, "limit": 5}

        provider_response = await provider_registry.execute_via_a2a(
            provider.name,
            ProviderRequest(
                action=action,
                payload=payload,
            )
        )
        provider_result = (
            provider_response.result
            if isinstance(provider_response.result, dict)
            else {}
        )
        results = _memory_provider_results(provider_response.result)
        metadata.update(
            {
                "executor": provider.name,
                "memory_results_count": len(results),
                "provider_status": provider_response.status,
                "provider_error": provider_response.error,
                "memory_results": results,
                "a2a_used": True,
                "memory_answer": provider_result.get("answer"),
                "memory_facts": provider_result.get("facts") or [],
            }
        )
        if action == "remember":
            metadata["memory_content"] = remembered_content

        if provider_response.error:
            return (
                f"Erreur du provider mémoire : {provider_response.error}",
                provider.name,
                {**metadata, "error": provider_response.error},
            )

        if action == "remember":
            provider_metadata = provider_result.get("metadata") or {}
            return (
                str(
                    provider_metadata.get("natural_response")
                    or f"C’est mémorisé : {remembered_content}"
                ),
                provider.name,
                metadata,
            )

        if action == "forget":
            forgotten = int(provider_result.get("forgotten") or 0)
            metadata["memory_forgotten_count"] = forgotten
            return (
                "C’est oublié." if forgotten else "Je n’ai trouvé aucune connaissance à oublier.",
                provider.name,
                metadata,
            )

        if provider_result.get("answer"):
            return (
                str(provider_result["answer"]),
                provider.name,
                metadata,
            )

        if not results:
            return (
                f"Je n’ai trouvé aucun souvenir correspondant à « {memory_query} ».",
                provider.name,
                metadata,
            )

        header = (
            f"J’ai trouvé {len(results)} résultat en mémoire :"
            if len(results) == 1
            else f"J’ai trouvé {len(results)} résultats en mémoire :"
        )
        lines = [f"- {item['content']}" for item in results]
        return "\n".join([header, *lines]), provider.name, metadata

    async def _execute_knowledge_provider(
        self,
        query: str,
        decision: OrchestratorDecision,
    ) -> tuple[str, str, dict[str, Any]]:
        """Mirroir simplifié de _execute_memory_provider — lecture seule,
        une seule action utile ("query", ou "documents" pour lister)."""
        kind = decision.intent.removeprefix("knowledge_") or "query"
        providers = provider_registry.by_type("knowledge")
        provider_info = providers[0] if providers else None
        provider = provider_registry.get(provider_info.name) if provider_info else None

        metadata = {
            "selected_route": "knowledge_provider",
            "executor": provider_info.name if provider_info else "knowledge_provider",
            "fallback_used": False,
            "retries": 0,
            "knowledge_kind": kind,
            "llm_used": False,
        }

        if provider is None:
            return (
                "La base de connaissances n'est pas disponible.",
                "knowledge_provider",
                {**metadata, "error": "knowledge provider unavailable"},
            )

        result = await build_knowledge_response_async(kind, query)
        metadata.update(
            {
                "executor": provider.name,
                "source": result.get("source"),
                "a2a_used": result.get("a2a_used", False),
                "knowledge_results": result.get("knowledge_results", []),
            }
        )
        if "error" in result:
            metadata["error"] = result["error"]

        return result["response"], provider.name, metadata

    async def _execute_agent_admin(self, query: str) -> tuple[str, str, dict[str, Any]]:
        """Active, désactive ou supprime un agent, via l'API HTTP de Goal.

        Le registre d'agents et leurs fichiers vivent côté Goal, éventuellement
        sur une autre machine : le Core n'y accède jamais directement (la
        version de septembre, 9f4e3e6/e84fb0b/3a56831, modifiait un registre en
        mémoire du Core et effaçait des fichiers sur le disque de Goal).
        La suppression exige une confirmation qui répète le nom de l'agent :
        sans état côté Core, elle fonctionne d'un appareil ou d'un processus
        à l'autre.
        """
        from server.common.goal_client import GoalClientError, get_goal_client

        parsed = _parse_agent_admin(query)
        assert parsed is not None
        action, name = parsed
        metadata: dict[str, Any] = {"agent": name, "agent_action": action, "llm_used": False}

        if action == "delete":
            return (
                f"Supprimer l'agent {name} est irréversible (une sauvegarde est "
                f"conservée côté Goal). Pour confirmer, réponds : "
                f"« confirme la suppression de l'agent {name} ».",
                "agent_admin",
                metadata,
            )

        client = get_goal_client()
        try:
            if action == "delete_confirm":
                result = await client.delete_agent(name)
            else:
                result = await client.set_agent_enabled(name, action == "enable")
        except GoalClientError as exc:
            logger.warning("agent_admin_goal_unreachable action=%s agent=%s error=%s", action, name, exc)
            return (
                f"Goal est injoignable : impossible de traiter l'agent {name} pour le moment.",
                "agent_admin",
                {**metadata, "error": str(exc)},
            )

        status = str(result.get("status") or "")
        agent = str(result.get("agent") or name)
        metadata["goal_result"] = result
        if status == "not_found":
            return f"Agent introuvable : {agent}.", "agent_admin", metadata
        if status == "refused":
            return (
                f"L'agent {agent} est protégé : Goal refuse de le modifier.",
                "agent_admin",
                metadata,
            )
        if status == "disabled":
            return (
                f"Agent {agent} désactivé. Pour le remettre en service : "
                f"« réactive l'agent {agent} ».",
                "agent_admin",
                metadata,
            )
        if status == "enabled":
            return f"Agent {agent} réactivé.", "agent_admin", metadata
        if status == "deleted":
            backup = (result.get("backup") or {}).get("backup_path")
            suffix = f" Sauvegarde : {backup}." if backup else ""
            return f"Agent {agent} supprimé.{suffix}", "agent_admin", metadata
        return (
            f"Goal n'a pas pu traiter l'agent {agent} ({status or 'réponse inattendue'}).",
            "agent_admin",
            {**metadata, "error": status or "unexpected_goal_response"},
        )

    async def _fetch_memory_context(self, query: str) -> str | None:
        """Résumé mémoire (Oblivia) à injecter dans le prompt de conversation
        générale. Fail-open : ne doit jamais bloquer ni faire échouer la
        conversation si le service memory est indisponible ou lent.
        Rétabli : cde7ea0, perdu avec 58ab382."""
        del query
        providers = provider_registry.by_type("memory")
        provider_info = providers[0] if providers else None
        if provider_info is None:
            return None
        provider = provider_registry.get(provider_info.name)
        if provider is None:
            return None
        try:
            response = await asyncio.wait_for(
                provider.execute(
                    ProviderRequest(
                        action="recall",
                        payload={"query": "que sais tu de moi", "limit": 10},
                    ),
                ),
                timeout=5.0,
            )
        except Exception:
            logger.warning("memory_context_fetch_failed", exc_info=True)
            return None
        if response.error:
            return None
        result = response.result if isinstance(response.result, dict) else {}
        answer = result.get("answer")
        return str(answer) if answer else None

    def _schedule_observe(self, query: str) -> None:
        """Envoie le message brut à POST /memory/observe en tâche de fond.

        La version d'origine attendait jusqu'à 3 s avant de répondre, puis
        abandonnait la requête alors que memory continuait de la traiter :
        jusqu'à 3 s de latence ajoutée à chaque message, sans garantie que
        l'observation aboutisse. Une référence est gardée pour que la tâche
        ne soit pas collectée en cours de route.
        """
        try:
            task = asyncio.get_running_loop().create_task(
                self._send_to_oblivia_observe(query)
            )
        except RuntimeError:  # pas de boucle active (appel synchrone)
            return
        _OBSERVE_TASKS.add(task)
        task.add_done_callback(_OBSERVE_TASKS.discard)

    async def _send_to_oblivia_observe(self, query: str) -> None:
        providers = provider_registry.by_type("memory")
        provider_info = providers[0] if providers else None
        if provider_info is None:
            return
        provider = provider_registry.get(provider_info.name)
        if provider is None:
            return
        try:
            await asyncio.wait_for(
                provider.execute(
                    ProviderRequest(
                        action="observe",
                        payload={"text": query, "source": "utilisateur"},
                    ),
                ),
                timeout=260.0,
            )
        except Exception:
            logger.warning("oblivia_observe_forward_failed", exc_info=True)

    async def _execute_llm_provider(
        self,
        query: str,
        decision: OrchestratorDecision,
    ) -> tuple[str, str, dict[str, Any]]:
        providers = provider_registry.by_type("llm")
        provider_info = providers[0] if providers else None
        provider = provider_registry.get(provider_info.name) if provider_info else None

        metadata = {
            "selected_route": "llm_provider",
            "executor": provider_info.name if provider_info else "llm",
            "fallback_used": False,
            "retries": 0,
            "provider_status": provider_info.status if provider_info else "unavailable",
            "llm_used": True,
            "llm_provider": provider_info.name if provider_info else "llm",
            "llm_action": "generate",
        }

        if provider is None:
            return (
                "Le provider LLM n'est pas disponible.",
                "llm",
                {**metadata, "error": "llm provider unavailable"},
            )

        memory_context = await self._fetch_memory_context(query)
        prompt = (
            f"Contexte connu sur l'utilisateur : {memory_context}\n\n{query}"
            if memory_context
            else query
        )
        metadata["memory_context_used"] = bool(memory_context)

        provider_response = await provider.execute(
            ProviderRequest(
                action="generate",
                payload={
                    "prompt": prompt,
                    "task_type": "chat",
                    "context": {},
                    "model_preference": "auto",
                },
            )
        )
        result = provider_response.result if isinstance(provider_response.result, dict) else {}
        model = str(result.get("model_used") or "")
        metadata.update(
            {
                "executor": provider.name,
                "provider_status": provider_response.status,
                "provider_error": provider_response.error,
                "llm_provider": provider.name,
                "model": model or None,
                "latency_ms": result.get("latency_ms"),
                "warning": result.get("warning"),
            }
        )

        if provider_response.error:
            return (
                f"Erreur du provider LLM : {provider_response.error}",
                provider.name,
                {**metadata, "error": provider_response.error},
            )

        text = str(result.get("result") or "")
        if not text.strip():
            # Echec PARTIEL du service LLM : il a repondu 200, donc ni
            # `raise_for_status` ni `provider_response.error` ne se declenchent,
            # mais le texte est vide et la cause est releguee en `warning`
            # (typiquement un ReadTimeout vers Ollama apres retries). Sans ce
            # garde-fou, Core renvoyait `response: ""` avec `error: null` :
            # l'appelant ne pouvait pas distinguer une panne d'une reponse
            # legitimement vide. Mesure du 03/09/2026 : 265 s d'attente pour
            # une chaine vide et aucune erreur.
            # Correction initiale 80d6794, perdue lors de la reintegration du
            # Core (58ab382), retablie ici.
            cause = result.get("warning") or "reponse vide du service LLM"
            logger.error(
                "llm_provider_empty_response provider=%s cause=%s",
                provider.name,
                cause,
            )
            return (
                "Le LLM n'a pas produit de reponse. Reessaie dans un instant.",
                provider.name,
                {**metadata, "error": str(cause)},
            )

        return text, provider.name, metadata


    async def _execute_registry(
        self,
        query: str,
        decision: OrchestratorDecision,
    ) -> tuple[str, str, dict[str, Any]]:
        """Handle registry queries."""
        # Determine what the user wants
        normalized = _normalize(query)
        services = service_registry.list_services()
        if not services:
            response = "Aucun service enregistré."
        else:
            target = _registry_target(normalized)
            if target is not None:
                matching = [
                    service
                    for service in services
                    if _service_matches_registry_target(service, target)
                ]
                if matching:
                    service = matching[0]
                    response = (
                        f"Le service {service['service_name']} fournit {target} "
                        f"(statut : {service.get('status', 'unknown')})."
                    )
                else:
                    response = f"Aucun service enregistré ne fournit {target}."
            # Check if user asks for stopped services
            elif any(
                k in normalized
                for k in ["arrete", "hors ligne", "stop", "down"]
            ):
                stopped = [s for s in services if s.get("status") != "healthy"]
                if not stopped:
                    response = "Tous les services sont en cours d'exécution (healthy)."
                else:
                    lines = [f"- {s['service_name']} : {s.get('status', 'inconnu')}" for s in stopped]
                    response = "Services arrêtés :\n" + "\n".join(lines)
            else:
                # Default: list all services with status
                lines = [f"- {s['service_name']} : {s.get('status', 'inconnu')}" for s in services]
                response = "Services enregistrés :\n" + "\n".join(lines)
        metadata = {
            "selected_route": "registry_provider",
            "executor": "registry_module",
            "fallback_used": False,
            "retries": 0,
        }
        return response, "registry_module", metadata

    async def _execute_topology(
        self,
        query: str,
        decision: OrchestratorDecision,
    ) -> tuple[str, str, dict[str, Any]]:
        """Handle topology queries."""
        topology = build_topology(service_registry)
        status = topology.get("status", "inconnu")
        service_count = topology.get("service_count", 0)
        healthy = topology.get("healthy_count", 0)
        degraded = topology.get("degraded_count", 0)
        offline = topology.get("offline_count", 0)
        # Build a friendly summary
        lines = []
        for svc in topology.get("services", []):
            lines.append(f"- {svc['name']} ({svc['status']}) : {svc['host']}:{svc['port']}")
        detail = "\n".join(lines) if lines else "Aucun service."
        response = (f"Topologie du système :\n"
                    f"État global : {status}\n"
                    f"Services : {service_count} (sains : {healthy}, dégradés : {degraded}, hors ligne : {offline})\n"
                    f"Détail :\n{detail}")
        metadata = {
            "selected_route": "topology_provider",
            "executor": "topology_module",
            "fallback_used": False,
            "retries": 0,
        }
        return response, "topology_module", metadata
    def _get_capability_resolver(self) -> Any:
        if self._capability_resolver is None:
            from modules.capabilities.resolver import CapabilityResolver

            self._capability_resolver = CapabilityResolver()
        return self._capability_resolver

    def _get_runtime_governor(self) -> Any:
        if self._runtime_governor is None:
            from core.runtime.governor import get_runtime_governor

            self._runtime_governor = get_runtime_governor()
        return self._runtime_governor

    def _get_agent_runtime(self) -> Any:
        if self._agent_runtime_factory is None:
            from agents.runtime.runtime import get_agent_runtime

            self._agent_runtime_factory = get_agent_runtime
        return self._agent_runtime_factory()

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
    Intent.PC_REMOTE,
}


@dataclass(frozen=True)
class AgentInvocation:
    agent_slug: str
    agent_input: str


def _normalize(text: str) -> str:
    return normalize_text(text)


def _registry_target(normalized_query: str) -> str | None:
    if "home assistant" in normalized_query:
        return "Home Assistant"
    if "memoire" in normalized_query:
        return "la mémoire"
    if re.search(r"\bllms?\b", normalized_query):
        return "les LLM"
    return None


def _service_matches_registry_target(
    service: dict[str, Any],
    target: str,
) -> bool:
    name = str(service.get("service_name", "")).lower()
    capabilities = {
        str(capability).lower()
        for capability in service.get("capabilities", [])
    }
    if target == "Home Assistant":
        return name == "homeassistant" or "home_automation" in capabilities
    if target == "la mémoire":
        return name == "memory" or bool(
            capabilities & {"memory", "sqlite", "obsidian", "context_storage"}
        )
    if target == "les LLM":
        return name == "llm" or bool(
            capabilities & {"text_generation", "chat", "completion"}
        )
    return False


def _parse_agent_invocation(query: str) -> AgentInvocation | None:
    raw = query.strip()
    if not raw:
        return None

    if raw.lower().startswith("/agent"):
        try:
            arguments = shlex.split(raw)
        except ValueError:
            return None
        if len(arguments) < 3 or arguments[:2] != ["/agent", "run"]:
            return None
        slug = _clean_invoked_agent_slug(arguments[2])
        if not slug:
            return None
        agent_input = ""
        if "--input" in arguments[3:]:
            input_index = arguments.index("--input", 3)
            agent_input = " ".join(arguments[input_index + 1 :]).strip()
        return AgentInvocation(slug, agent_input)

    execution_match = re.match(
        r"^\s*(?:lance|ex[eé]cute)\s+"
        r"(?:(?:l['’]?\s*agent|agent)\s+)?"
        r"([A-Za-z0-9_.-]+)"
        r"(?:\s*:\s*(.*))?\s*$",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if execution_match:
        slug = _clean_invoked_agent_slug(execution_match.group(1))
        if slug in {"la", "le", "les", "prochaine", "prochain"}:
            return None
        return AgentInvocation(
            slug,
            str(execution_match.group(2) or "").strip(),
        )

    request_match = re.match(
        r"^\s*demande\s+[aà]\s+([A-Za-z0-9_.-]+)"
        r"(?:\s+de\s+r[eé]pondre)?"
        r"(?:\s*:\s*(.*))?\s*$",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if request_match:
        slug = _clean_invoked_agent_slug(request_match.group(1))
        if not slug:
            return None
        return AgentInvocation(slug, str(request_match.group(2) or "").strip())

    return None


def _clean_invoked_agent_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "", value.lower()).replace("-", "_")


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


def _extract_memory_search_query(query: str) -> str:
    normalized = _normalize(query).strip(" ?!.:,;")
    patterns = (
        r"^qu\s+as\s+tu\s+memorise\s+sur\s+(.+)$",
        r"^que\s+sais\s+tu\s+sur\s+(.+)$",
        r"^retrouve\s+mes\s+notes\s+sur\s+(.+)$",
        r"^(?:recherche|cherche|retrouve)\s+(?:dans\s+ta\s+memoire\s+)?(.+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, normalized)
        if match:
            value = match.group(1).strip(" ?!.:,;")
            if value:
                return value
    return normalized or query.strip()


def _extract_memory_recall_query(query: str) -> str:
    normalized = " ".join(
        re.sub(r"[^a-z0-9 ]+", " ", _normalize(query)).split()
    )
    patterns = (
        r"^oublie\s+ce\s+que\s+tu\s+sais\s+sur\s+(.+)$",
        r"^oublie\s+que\s+(.+)$",
        r"^efface\s+de\s+ta\s+memoire\s+(.+)$",
        r"^qu\s+as\s+tu\s+memorise\s+sur\s+(.+)$",
        r"^que\s+sais\s+tu\s+sur\s+(.+)$",
        r"^tu\s+te\s+souviens\s+(?:de|sur)?\s*(.+)$",
        r"^te\s+rappelles\s+tu\s+(?:de|sur)?\s*(.+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, normalized)
        if match:
            value = match.group(1).strip(" ?!.:,;")
            if value:
                return value
    knowledge_questions = (
        "qui est papa",
        "comment s appelle ma femme",
        "qu est ce que j aime boire",
        "que j aime boire",
        "comment je m appelle",
        "qui est mon fils",
        "ou est ce que j habite",
        "ou est ce que je travaille",
        "ou est ce que j habitais avant",
        "ou habitais je avant",
        "ou ai je vecu",
        "dans quelles villes ai je vecu",
        "ou travaillais je avant",
        "comment je m appelais avant",
        "comment s appelait ma femme avant",
        "j aime quoi",
        "qui suis je",
        "parle moi de moi",
        "presente moi",
        "que sais tu de moi",
        "fais un resume de ce que tu sais sur moi",
        "qui est ma femme",
        "qui est mon epouse",
        "ou ai je travaille",
        "qu est ce que j aime",
        "qu est ce que j aimais avant",
        "quels anciens souvenirs possedes tu",
        "quelles informations ne sont plus actuelles",
        "quelles informations sont obsoletes",
        "montre moi tout ce que tu sais",
        "montre toute ma memoire",
        "quels souvenirs possedes tu",
        "combien de souvenirs as tu sur moi",
        "quels types d informations connais tu",
        "quels predicats connais tu sur moi",
        "ai je des informations contradictoires",
        "as tu detecte des conflits",
        "y a t il des souvenirs retractes",
        "as tu des informations douteuses",
        "y a t il des donnees obsoletes",
        "qui habite avec moi",
        "qui depend de moi",
        "qui fait partie de mon foyer",
        "si je demenage qui demenage probablement avec moi",
        "qui est lie a moi",
        "qui fait partie de ma famille",
        "qui partage ma vie",
        "tu me connais bien",
        "est ce que tu te souviens de moi",
        "as tu appris des choses sur moi",
        "qu est ce que tu retiens principalement de moi",
        "qu est ce qui me caracterise",
        "que pourrais tu raconter sur moi a quelqu un",
        "si tu devais me presenter que dirais tu",
        "quelle est la derniere chose importante que tu as apprise sur moi",
        "quel est mon telephone",
        "quel telephone j utilise",
        "quel smartphone ai je",
        "quels appareils je possede",
        "qu est ce que j ai achete",
        "tu te souviens de mon telephone",
        "combien ai je d enfants",
        "comment s appellent mes enfants",
        "qui sont mes enfants",
    )
    if any(pattern in normalized for pattern in knowledge_questions):
        return normalized
    if re.fullmatch(r"qui est [a-z][a-z0-9 ]*", normalized):
        return normalized
    return ""


def _extract_memory_remember_content(query: str) -> str:
    normalized = query.strip()
    cleaned = _normalize(query)
    prefixes = (
        "memorise que",
        "retiens que",
        "souviens toi que",
        "note que",
        "garde en memoire que",
    )
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            words = normalized.split()
            return " ".join(words[len(prefix.split()) :]).strip(" .")
    return normalized


_OBSERVE_TASKS: set[asyncio.Task] = set()

# Routes dont le message n'est PAS envoyé à /memory/observe.
_ROUTES_SANS_OBSERVATION = frozenset({
    # La route mémoire fait déjà le travail (correction du 08/09/2026) :
    # - écriture : « Retiens que mon vélo est un Decathlon Riverside. »
    #   déclenchait les deux chaînes d'extraction et produisait
    #   `habite_a = Riverside` ;
    # - lecture : la question était stockée avant la recherche et
    #   ressortait dans sa propre réponse.
    "memory_provider",
    # Rien à apprendre, et chaque observation lance une génération Ollama
    # côté memory : sur 2 cœurs sans GPU, un « Bonjour » observé occupait le
    # modèle pendant la réponse suivante.
    "smalltalk",
    "help_provider",
    "agent_admin",
})


def _message_a_observer(decision: OrchestratorDecision) -> bool:
    return decision.selected_route not in _ROUTES_SANS_OBSERVATION


def _memory_provider_action(
    query: str,
    memory_result: dict[str, Any],
    decision: OrchestratorDecision,
) -> str:
    if decision.intent == Intent.MEMORY_SEARCH.value:
        return "search"
    kind = str(memory_result.get("kind") or "")
    if kind in {"remember", "recall", "search", "forget", "status"}:
        return kind
    normalized = _normalize(query)
    if any(
        token in normalized
        for token in ("memorise", "retiens", "souviens toi que", "note que")
    ):
        return "remember"
    return "recall"


def _memory_provider_results(value: Any) -> list[dict[str, str]]:
    if isinstance(value, dict):
        value = value.get("results") or []
    if not isinstance(value, list):
        return []

    results: list[dict[str, str]] = []
    for item in value:
        if hasattr(item, "model_dump"):
            item = item.model_dump(mode="json")
        if not isinstance(item, dict):
            continue
        record = item.get("record")
        if hasattr(record, "model_dump"):
            record = record.model_dump(mode="json")
        if not isinstance(record, dict):
            continue
        content = _memory_result_content(str(record.get("content") or ""))
        if not content:
            continue
        results.append(
            {
                "content": content,
                "backend": str(item.get("backend") or ""),
                "score": str(item.get("score") or ""),
            }
        )
    return results


def _memory_result_content(content: str, limit: int = 220) -> str:
    cleaned = " ".join(content.replace("\n", " ").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _is_self_model_request(query: str) -> bool:
    return any(
        token in query
        for token in (
            "que sais tu de toi meme",
            "etat interne",
            "modele interne",
            "modele de toi",
            "representation interne",
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
        "capacite specialisee",
        "paques",
        "sous reseau",
        "subnet",
    )
    return any(token in query for token in durable + complex_request)


def _detect_gateway_domain(query: str) -> str | None:
    """Domaine externe (mail, contacts, notes, reminders, calendar, repos,
    docs) porte par le registre de passerelles (server/gateways), detecte
    avec confiance elevee, sinon None.

    Calcule une fois, tot dans `decide()`, plutot que dans
    `_requires_specialized_resolution` plus bas dans la cascade : le
    classifieur d'intent misclasse ces phrases (« montre mes contacts » ->
    intent=system_status) et la branche status_provider les captait avant.
    Sans cette detection, elles tombaient dans le chat LLM generique, qui
    inventait une reponse. Regression constatee le 26/09/2026.
    """
    from modules.capabilities.decision_engine import GATEWAY_DOMAINS
    from modules.capabilities.domain_classifier import DomainClassifier

    classification = DomainClassifier().classify(query)
    if classification.domain in GATEWAY_DOMAINS and classification.confidence >= 0.9:
        return classification.domain
    return None


# ── Gestion des agents (activation, désactivation, suppression) ────────────
# Le mot « agent » est obligatoire : la version de septembre acceptait aussi
# « active la … » et « supprime l'… », ce qui captait « active la lumière ».
# « active agent X » n'est PAS repris ici : c'est la promotion d'un agent
# généré (agent_router._is_promote_request), sens existant conservé.

_AGENT_ADMIN_INTENTS = {
    "enable": Intent.AGENT_ENABLE,
    "disable": Intent.AGENT_DISABLE,
    "delete": Intent.AGENT_DELETE,
    "delete_confirm": Intent.AGENT_DELETE_CONFIRM,
}
_AGENT_ADMIN_TARGET = r"(?:l'\s*|l\s+|le\s+)?agent\s+([A-Za-z0-9_.-]+)\s*[.!]?\s*$"
_AGENT_ADMIN_PATTERNS = (
    ("delete_confirm", r"^\s*confirmer?\s+(?:la\s+)?suppression\s+(?:de\s+)?" + _AGENT_ADMIN_TARGET),
    ("disable", r"^\s*(?:d[ée]sactiver?|arr[êe]ter?|stopper?)\s+" + _AGENT_ADMIN_TARGET),
    ("enable", r"^\s*r[ée]activer?\s+" + _AGENT_ADMIN_TARGET),
    ("delete", r"^\s*(?:supprimer?|effacer?)\s+" + _AGENT_ADMIN_TARGET),
)


def _parse_agent_admin(query: str) -> tuple[str, str] | None:
    """(action, nom de l'agent) pour une commande de gestion d'agent, sinon None.

    Lu sur la phrase d'origine : la normalisation remplace « _ » et « - » par
    des espaces et rendrait « meteo_agent » méconnaissable.
    """
    raw = str(query or "").replace("’", "'")
    for action, pattern in _AGENT_ADMIN_PATTERNS:
        match = re.match(pattern, raw, flags=re.IGNORECASE)
        if match:
            # Les noms peuvent contenir des points : le point final d'une
            # phrase (« stoppe agent veille_agent. ») n'en fait pas partie.
            name = match.group(1).rstrip(".")
            if name:
                return action, name
    return None


_PC_REMOTE_ACTION_MARKERS = {
    "ouvre", "ouvrir", "lance", "lancer", "demarre", "demarrer",
    "ferme", "fermer", "arrete", "arreter", "stoppe", "stopper",
    "tue", "tuer", "liste", "lister", "affiche", "afficher",
    "montre", "montrer",
}

_PC_REMOTE_EXPLICIT_PHRASES = (
    "pc distant", "ordinateur distant", "commande mon pc",
    "sur mon pc", "sur le serveur",
)


def _detect_pc_remote_action(query: str) -> bool:
    """Commande de contrôle PC distant (tool pc_remote), détectée de façon
    déterministe : un verbe d'action ET (une formule explicite OU le nom/id
    d'un PC déclaré dans neron.yaml, pc_remote.devices).

    Le PC est piloté en HTTP via son agent neronRemote : compatible avec un
    Core et un PC sur des machines distinctes. Registre illisible ou
    pc_remote désactivé : pas de détection, jamais d'exception.
    """
    if not (set(query.split()) & _PC_REMOTE_ACTION_MARKERS):
        return False

    if any(phrase in query for phrase in _PC_REMOTE_EXPLICIT_PHRASES):
        return True

    try:
        from integrations.pc_remote.config import load_devices

        devices = load_devices().values()
    except Exception:
        return False

    for device in devices:
        if device.id.replace("_", " ") in query or _normalize(device.name) in query:
            return True
    return False


def _requires_goal_pipeline(query: str) -> bool:
    return any(
        token in query
        for token in (
            "analyse cette demande complexe",
            "tache complexe",
            "demande complexe",
            "construis ",
            "construire ",
            "construction ",
        )
    )


def _is_goal_engine_request(query: str) -> bool:
    return any(
        token in query
        for token in (
            "utilise un agent",
            "utilise l agent",
            "utiliser un agent",
            "agent de diagnostic",
            "prepare un plan pour creer un agent",
        )
    )


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
        Intent.PC_REMOTE: "pc_remote_agent",
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


