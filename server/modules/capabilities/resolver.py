from __future__ import annotations

import ipaddress
import re
from datetime import date
from typing import Any

from modules.capabilities.models import (
    Capability,
    CapabilityDecision,
    CapabilityRequest,
    CapabilityResult,
    ResolverAnalysis,
)
from modules.capabilities.decision_engine import DecisionEngine
from modules.capabilities.intent_provider import (
    IntentProvider,
    RuleBasedIntentProvider,
)
from modules.capabilities.matcher import CapabilityMatcher
from modules.capabilities.registry import CapabilityRegistry
from modules.capabilities.router import CapabilityRouter, normalize_text


ASYNC_RESPONSE = "Je m’en occupe. Je te reviens avec la réponse dès que c’est prêt."
ASYNC_AGENT_RESPONSE = "Je m’en occupe. Je te préviens quand l’analyse est prête."


class CapabilityResolver:
    def __init__(
        self,
        *,
        registry: CapabilityRegistry | None = None,
        router: CapabilityRouter | None = None,
        goal_manager: Any | None = None,
        execution_engine: Any | None = None,
        background_runner: Any | None = None,
        runtime_manager: Any | None = None,
        tool_creator: Any | None = None,
        task_scheduler: Any | None = None,
        intent_provider: IntentProvider | None = None,
        matcher: CapabilityMatcher | None = None,
        decision_engine: DecisionEngine | None = None,
    ) -> None:
        self.registry = registry or CapabilityRegistry()
        self.router = router or CapabilityRouter()
        self.intent_provider = intent_provider or RuleBasedIntentProvider()
        self.matcher = matcher or CapabilityMatcher()
        self.decision_engine = decision_engine or DecisionEngine()
        self._goal_manager = goal_manager
        self._execution_engine = execution_engine
        self._background_runner = background_runner
        self._runtime_manager = runtime_manager
        self._tool_creator = tool_creator
        self._task_scheduler = task_scheduler
        self._requests: dict[str, CapabilityResult] = {}
        self._analyses: dict[str, ResolverAnalysis] = {}

    async def resolve(self, request: CapabilityRequest) -> CapabilityResult | None:
        decision = await self.decide_async(request)
        if decision is None:
            return None

        if decision.decision == "ask_human_validation":
            return self._remember(
                request,
                CapabilityResult(
                    status="validation_required",
                    response="Cette action nécessite une validation humaine avant de continuer.",
                    decision=decision,
                ),
            )
        if decision.decision == "reject":
            return self._remember(
                request,
                CapabilityResult(
                    status="rejected",
                    response="Je ne peux pas exécuter cette demande en sécurité.",
                    decision=decision,
                ),
            )
        if decision.decision == "direct_answer":
            return self._remember(
                request,
                CapabilityResult(
                    status="completed",
                    response=self._direct_answer(request.text),
                    decision=decision,
                ),
            )
        if decision.decision == "use_existing_tool":
            capability = self._selected_capability(
                decision.selected_tool,
                capability_type="tool",
            )
            return self._remember(
                request,
                await self._execute_capability(request, decision, capability),
            )
        if decision.decision == "use_existing_agent":
            capability = self._selected_capability(
                decision.selected_agent,
                capability_type="agent",
            )
            return self._remember(
                request,
                await self._execute_capability(request, decision, capability),
            )
        if decision.decision in {"create_tool", "create_agent"}:
            return self._remember(
                request,
                await self._queue_creation(request, decision),
            )
        if decision.decision == "use_gateway":
            return self._remember(request, self._execute_gateway(decision))
        if decision.decision == "propose_gateway_connection":
            return self._remember(request, self._propose_gateway_connection(decision))
        if decision.decision == "no_gateway_available":
            return self._remember(request, self._no_gateway_available(decision))
        return None

    def decide(self, request: CapabilityRequest) -> CapabilityDecision | None:
        initial = self.router.classify(request.text)
        if initial is not None and initial.decision in {
            "ask_human_validation",
            "reject",
            "direct_answer",
        }:
            return initial

        analysis = self.analyze(request.text)
        return self._capability_decision(request, initial, analysis)

    async def decide_async(
        self,
        request: CapabilityRequest,
    ) -> CapabilityDecision | None:
        initial = self.router.classify(request.text)
        if initial is not None and initial.decision in {
            "ask_human_validation",
            "reject",
            "direct_answer",
        }:
            return initial
        analysis = await self.analyze_async(request.text)
        self._analyses[request.request_id] = analysis
        return self._capability_decision(request, initial, analysis)

    def _capability_decision(
        self,
        request: CapabilityRequest,
        initial: CapabilityDecision | None,
        analysis: ResolverAnalysis,
    ) -> CapabilityDecision | None:
        if analysis.decision == "execute_agent":
            return CapabilityDecision(
                decision="use_existing_agent",
                confidence=analysis.confidence,
                reason=analysis.reason,
                capability_type="agent",
                selected_agent=analysis.matched_agent,
                safety_level=initial.safety_level if initial else "low",
            )
        if analysis.decision == "execute_tool":
            return CapabilityDecision(
                decision="use_existing_tool",
                confidence=analysis.confidence,
                reason=analysis.reason,
                capability_type="tool",
                selected_tool=analysis.matched_tool,
                safety_level=initial.safety_level if initial else "low",
            )
        if analysis.decision in {"create_tool", "create_agent"}:
            creation_type = analysis.decision.removeprefix("create_")
            return CapabilityDecision(
                decision=analysis.decision,
                confidence=analysis.confidence,
                reason=analysis.reason,
                capability_type=creation_type,
                requires_creation=True,
                creation_type=creation_type,
                async_required=True,
                safety_level=(
                    "medium" if creation_type == "agent" else "low"
                ),
            )
        if analysis.decision in {
            "use_gateway",
            "propose_gateway_connection",
            "no_gateway_available",
        }:
            return CapabilityDecision(
                decision=analysis.decision,
                confidence=analysis.confidence,
                reason=analysis.reason,
                capability_type="gateway",
                gateway_connector_id=analysis.gateway_connector_id,
                safety_level=initial.safety_level if initial else "low",
            )
        if initial is None:
            return None
        return self._legacy_decision(request, initial)

    def analyze(self, text: str) -> ResolverAnalysis:
        provider = self.intent_provider
        if not hasattr(provider, "classify_sync"):
            raise TypeError(
                "The active IntentProvider must expose classify_sync until "
                "the resolver becomes fully asynchronous"
            )
        understanding = provider.classify_sync(text)
        return self._analysis_from_understanding(text, understanding)

    async def analyze_async(self, text: str) -> ResolverAnalysis:
        understanding = await self.intent_provider.classify(text)
        return self._analysis_from_understanding(text, understanding)

    def _analysis_from_understanding(
        self,
        text: str,
        understanding: Any,
    ) -> ResolverAnalysis:
        match = self.matcher.match(
            text,
            understanding,
            self.registry.list_capabilities(),
        )
        decision, confidence, reason, extra = self.decision_engine.decide(
            text,
            understanding,
            match,
        )
        capability = match.capability if match is not None else None
        return ResolverAnalysis(
            text=text,
            domain=understanding.domain,
            intent=understanding.intent,
            decision=decision,
            confidence=round(confidence, 3),
            matched_agent=(
                capability.agent_slug or capability.slug
                if capability is not None
                and capability.capability_type == "agent"
                else None
            ),
            matched_tool=(
                capability.tool_slug or capability.slug
                if capability is not None
                and capability.capability_type == "tool"
                else None
            ),
            match_score=match.score if match is not None else None,
            missing_tools=list(match.missing_tools) if match is not None else [],
            provider=understanding.provider,
            reason=reason,
            gateway_connector_id=extra.get("gateway_connector_id"),
        )

    def _legacy_decision(
        self,
        request: CapabilityRequest,
        initial: CapabilityDecision,
    ) -> CapabilityDecision:
        if initial.capability_type == "agent":
            existing = self.registry.find_matching_agent(request.text)
            if existing is not None:
                return CapabilityDecision(
                    decision="use_existing_agent",
                    confidence=0.94,
                    reason=f"Capacité durable existante trouvée : {existing.slug}.",
                    capability_type="agent",
                    selected_agent=existing.agent_slug or existing.slug,
                    safety_level=initial.safety_level,
                )
        else:
            existing = self.registry.find_matching_tool(request.text)
            if existing is not None:
                return CapabilityDecision(
                    decision="use_existing_tool",
                    confidence=0.96,
                    reason=f"Tool existant trouvé : {existing.slug}.",
                    capability_type="tool",
                    selected_tool=existing.tool_slug or existing.slug,
                    safety_level=initial.safety_level,
                )
            existing_agent = self.registry.find_matching_agent(request.text)
            if existing_agent is not None:
                return CapabilityDecision(
                    decision="use_existing_agent",
                    confidence=0.9,
                    reason=f"Agent existant trouvé : {existing_agent.slug}.",
                    capability_type="agent",
                    selected_agent=existing_agent.agent_slug or existing_agent.slug,
                    safety_level=initial.safety_level,
                )
        return initial

    def _selected_capability(
        self,
        slug: str | None,
        *,
        capability_type: str,
    ) -> Capability | None:
        if not slug:
            return None
        for capability in self.registry.list_capabilities():
            selected_slug = (
                capability.agent_slug
                if capability_type == "agent"
                else capability.tool_slug
            )
            if capability.capability_type == capability_type and slug in {
                capability.slug,
                selected_slug,
            }:
                return capability
        return None

    async def get_result(self, request_id: str) -> CapabilityResult | None:
        result = self._requests.get(request_id)
        if result is None:
            result = self._restore_request_result(request_id)
            if result is not None:
                self._requests[request_id] = result
        if result is None or not result.goal_id or not result.async_started:
            return result
        status = self._goal_engine().get_goal_status(result.goal_id)
        if not status:
            return result
        current = str(status.get("status") or "pending")
        if current in {"queued", "running"}:
            result.status = current
            return result
        if current == "failed":
            result.status = "failed"
            result.error = str(status.get("error") or "La création de capacité a échoué.")
            result.response = "Je n’ai pas pu préparer cette capacité."
            return result

        result.status = "completed"
        result.project_id = status.get("project_id")
        result.agent_slug = status.get("agent_slug")
        if result.agent_slug:
            original_text = str(result.metadata.get("original_text") or "")
            executed = await self._run_agent(result.agent_slug, original_text)
            if executed.get("ok"):
                result.response = str(executed.get("response") or result.response)
            else:
                result.error = str(executed.get("error") or "Exécution impossible.")
        return result

    def _restore_request_result(self, request_id: str) -> CapabilityResult | None:
        for goal in self._goal_engine().list_goals():
            metadata = goal.get("metadata") or {}
            if str(metadata.get("capability_request_id") or "") != request_id:
                continue
            creation_type = str(metadata.get("creation_type") or "tool")
            decision = CapabilityDecision(
                decision=f"create_{creation_type}",
                confidence=1.0,
                reason="Demande de capacité restaurée depuis goal_runs.",
                capability_type=creation_type,
                requires_creation=True,
                creation_type=creation_type,
                async_required=True,
            )
            return CapabilityResult(
                status=str(goal.get("status") or "pending"),
                response=ASYNC_RESPONSE,
                async_started=True,
                goal_id=str(goal.get("goal_id") or ""),
                project_id=goal.get("project_id"),
                agent_slug=goal.get("agent_slug"),
                request_id=request_id,
                decision=decision,
                metadata={
                    "creation_type": creation_type,
                    "original_text": metadata.get("capability_original_text") or "",
                    "required_tools": list(metadata.get("required_tools") or []),
                    "created_tools": list(metadata.get("created_tools") or []),
                    "tool_creation_status": metadata.get(
                        "tool_creation_status",
                        "not_required",
                    ),
                    "scheduler_task_ids": list(
                        metadata.get("scheduler_task_ids") or []
                    ),
                    "task_id": metadata.get("task_id"),
                    "composite_task_id": metadata.get("composite_task_id"),
                },
            )
        return None

    async def _execute_capability(
        self,
        request: CapabilityRequest,
        decision: CapabilityDecision,
        capability: Capability | None,
    ) -> CapabilityResult:
        if capability is None:
            return CapabilityResult(
                status="failed",
                response="Je n’ai pas trouvé la capacité attendue.",
                error="capability_not_found",
                decision=decision,
            )
        try:
            if capability.source == "builtin_tool":
                response = await self._execute_builtin(capability.slug, request.text)
            else:
                runtime_result = await self._run_agent(
                    capability.agent_slug or capability.slug,
                    request.text,
                )
                if not runtime_result.get("ok"):
                    raise RuntimeError(runtime_result.get("error") or "runtime_execution_failed")
                response = str(runtime_result.get("response") or "")
            return CapabilityResult(
                status="completed",
                response=response,
                tool_slug=capability.tool_slug if capability.capability_type == "tool" else None,
                agent_slug=capability.agent_slug if capability.capability_type == "agent" else None,
                decision=decision,
            )
        except Exception as exc:
            return CapabilityResult(
                status="failed",
                response="Je n’ai pas pu exécuter cette demande.",
                error=str(exc),
                decision=decision,
            )

    def _execute_gateway(self, decision: CapabilityDecision) -> CapabilityResult:
        connector = self._gateway_connector(decision.gateway_connector_id)
        if connector is None:
            return CapabilityResult(
                status="failed",
                response="Le connecteur attendu n’est plus disponible.",
                error="gateway_not_found",
                decision=decision,
            )
        return CapabilityResult(
            status="completed",
            response=(
                f"Je suis connecté à {connector.name} pour ce type de demande, mais "
                "l’exécution de cette action précise n’est pas encore branchée côté Néron."
            ),
            decision=decision,
        )

    def _propose_gateway_connection(self, decision: CapabilityDecision) -> CapabilityResult:
        connector = self._gateway_connector(decision.gateway_connector_id)
        if connector is None:
            return CapabilityResult(
                status="failed",
                response="Le connecteur attendu n’est plus disponible.",
                error="gateway_not_found",
                decision=decision,
            )
        return CapabilityResult(
            status="action_required",
            response=(
                f"Je peux me connecter à {connector.name} pour ce type de demande, "
                f"mais ce n’est pas encore fait. {connector.connect_hint}"
            ),
            decision=decision,
        )

    def _no_gateway_available(self, decision: CapabilityDecision) -> CapabilityResult:
        return CapabilityResult(
            status="completed",
            response="Je n’ai pas encore de passerelle disponible pour ce type de demande.",
            decision=decision,
        )

    def _gateway_connector(self, connector_id: str | None) -> Any | None:
        if not connector_id:
            return None
        from gateways.registry import get_registry

        return get_registry().get(connector_id)

    async def _queue_creation(
        self,
        request: CapabilityRequest,
        decision: CapabilityDecision,
    ) -> CapabilityResult:
        creation_type = decision.creation_type or "tool"
        objective = self._creation_objective(request.text, creation_type)
        analysis = self._analyses.get(request.request_id)
        legacy_specs = self._tools().plan_tools_for_request(request.text)
        if legacy_specs:
            tool_preparation = self._tools().ensure_tools_for_request(request.text)
        elif analysis is not None:
            need = self._tools().plan_need(
                request.text,
                domain=analysis.domain.domain,
                intent=analysis.intent.action,
                required_tool_slugs=analysis.missing_tools,
                matched_capability=analysis.matched_agent,
            )
            tool_preparation = await self._tools().create_from_need(need)
            tool_preparation["tool_creation_status"] = (
                "ready"
                if tool_preparation.get("status") == "completed"
                else "failed"
            )
        else:
            tool_preparation = self._tools().ensure_tools_for_request(request.text)
        scheduler_chain = self._enqueue_scheduler_chain(
            request,
            tool_preparation,
        )
        scheduler_tasks = list(scheduler_chain.get("tasks") or [])
        composite_task = scheduler_chain.get("composite_task")
        metadata = {
            "orchestrated": True,
            "asynchronous": True,
            "internal_capability_request": True,
            "capability_request_id": request.request_id,
            "capability_original_text": request.text,
            "creation_type": creation_type,
            "source_channel": request.channel,
            "user_id": request.user_id,
            "required_tools": list(tool_preparation.get("required_tools") or []),
            "created_tools": list(tool_preparation.get("created_tools") or []),
            "tool_creation_status": str(
                tool_preparation.get("tool_creation_status") or "not_required"
            ),
            "scheduler_task_ids": [
                task.task_id for task in scheduler_tasks
            ],
            "task_id": scheduler_tasks[0].task_id if scheduler_tasks else None,
            "composite_task_id": (
                composite_task.task_id if composite_task is not None else None
            ),
        }
        manager = self._goals()
        goal = manager.create_goal(
            title=objective,
            priority="high" if request.channel == "telegram" else "medium",
            source=f"{request.channel}_capability",
            metadata=metadata,
            deduplicate=False,
        )
        goal_id = str(goal["id"])
        manager.update_status(goal_id, "queued", current_step="queued")
        self._goal_engine().enqueue_goal(
            goal_id,
            objective,
            f"{request.channel}_capability",
            metadata,
        )
        self._runner().submit(
            goal_id=goal_id,
            objective=objective,
            source=f"{request.channel}_capability",
        )
        return CapabilityResult(
            status="pending",
            response=(
                ASYNC_AGENT_RESPONSE
                if creation_type == "agent"
                else ASYNC_RESPONSE
            ),
            async_started=True,
            goal_id=goal_id,
            tool_slug=None,
            agent_slug=None,
            decision=decision,
            metadata={
                "creation_type": creation_type,
                "original_text": request.text,
                "required_tools": metadata["required_tools"],
                "created_tools": metadata["created_tools"],
                "tool_creation_status": metadata["tool_creation_status"],
                "scheduler_task_ids": metadata["scheduler_task_ids"],
                "task_id": metadata["task_id"],
                "composite_task_id": metadata["composite_task_id"],
            },
        )

    def _creation_objective(self, text: str, creation_type: str) -> str:
        if creation_type == "agent":
            if "agent" in normalize_text(text):
                return text
            return f"Créer un agent durable qui répond à cette demande : {text}"
        return (
            "Créer un agent d’exécution interne représentant un tool déterministe "
            f"(metadata creation_type=tool) pour répondre à : {text}"
        )

    async def _execute_builtin(self, slug: str, text: str) -> str:
        if slug == "date.current":
            today = date.today()
            weekdays = (
                "lundi", "mardi", "mercredi", "jeudi",
                "vendredi", "samedi", "dimanche",
            )
            months = (
                "janvier", "février", "mars", "avril", "mai", "juin",
                "juillet", "août", "septembre", "octobre", "novembre", "décembre",
            )
            return (
                f"Nous sommes {weekdays[today.weekday()]} "
                f"{today.day} {months[today.month - 1]} {today.year}."
            )
        if slug == "date.easter":
            year_match = re.search(r"\b(19|20|21)\d{2}\b", text)
            year = int(year_match.group(0)) if year_match else date.today().year
            easter = self._easter_date(year)
            months = (
                "janvier", "février", "mars", "avril", "mai", "juin",
                "juillet", "août", "septembre", "octobre", "novembre", "décembre",
            )
            return f"Pâques {year} tombe le {easter.day} {months[easter.month - 1]} {year}."
        if slug == "date.christmas_countdown":
            today = date.today()
            christmas = date(today.year, 12, 25)
            if today > christmas:
                christmas = date(today.year + 1, 12, 25)
            days = (christmas - today).days
            unit = "jour" if days == 1 else "jours"
            return f"Il reste {days} {unit} avant Noël ({christmas:%d/%m/%Y})."
        if slug == "network.subnet":
            match = re.search(r"(?<!\S)([0-9a-fA-F:.]+/\d{1,3})(?!\S)", text)
            if not match:
                return "Indique un réseau au format CIDR, par exemple 192.168.1.0/24."
            network = ipaddress.ip_network(match.group(1), strict=False)
            lines = [
                f"Réseau : {network.with_prefixlen}",
                f"Masque : {network.netmask}",
                f"Première adresse : {network.network_address}",
                f"Dernière adresse : {network.broadcast_address}",
                f"Nombre total d’adresses : {network.num_addresses}",
            ]
            if isinstance(network, ipaddress.IPv4Network):
                lines.append(f"Hôtes utilisables : {max(0, network.num_addresses - 2)}")
            return "\n".join(lines)
        if slug == "system.diagnostic":
            import psutil

            disk = psutil.disk_usage("/")
            memory = psutil.virtual_memory()
            return (
                "Diagnostic Néron : "
                f"CPU {psutil.cpu_percent(interval=None):.0f} %, "
                f"mémoire {memory.percent:.0f} %, "
                f"disque {disk.percent:.0f} % utilisés."
            )
        raise ValueError(f"Tool intégré inconnu : {slug}")

    def _direct_answer(self, text: str) -> str:
        query = normalize_text(text)
        if "merci" in query:
            return "Avec plaisir."
        return "Bonjour. Que puis-je faire pour toi ?"

    def _remember(
        self,
        request: CapabilityRequest,
        result: CapabilityResult,
    ) -> CapabilityResult:
        result.request_id = request.request_id
        self._requests[request.request_id] = result
        return result

    def _goals(self):
        if self._goal_manager is None:
            from goal.goals.goal_manager import get_goal_manager

            self._goal_manager = get_goal_manager()
        return self._goal_manager

    def _goal_engine(self):
        if self._execution_engine is None:
            from goal.goals.execution_engine import get_goal_execution_engine

            self._execution_engine = get_goal_execution_engine()
        return self._execution_engine

    def _runner(self):
        if self._background_runner is None:
            from goal.goals.background_runner import get_goal_background_runner

            self._background_runner = get_goal_background_runner()
        return self._background_runner

    def _runtime(self):
        if self._runtime_manager is None:
            from agents.runtime.runtime import get_agent_runtime

            self._runtime_manager = get_agent_runtime()
        return self._runtime_manager

    async def _run_agent(self, agent_slug: str, text: str) -> dict[str, Any]:
        runtime = self._runtime()
        if hasattr(runtime, "run_agent"):
            result = await runtime.run_agent(agent_slug, text)
            return result.to_dict() if hasattr(result, "to_dict") else dict(result)
        return await runtime.run(agent_slug, text)

    def _tools(self):
        if self._tool_creator is None:
            from tools.creator import get_tool_creator

            self._tool_creator = get_tool_creator()
        return self._tool_creator

    def _scheduler(self):
        if self._task_scheduler is None:
            from modules.scheduler.scheduler import get_task_scheduler

            self._task_scheduler = get_task_scheduler()
        return self._task_scheduler

    def _enqueue_scheduler_chain(
        self,
        request: CapabilityRequest,
        tool_preparation: dict[str, Any],
    ) -> dict[str, Any]:
        required_tools = list(tool_preparation.get("required_tools") or [])
        if required_tools != [
            "neron_log_reader_tool",
            "neron_log_error_filter_tool",
            "neron_log_summary_tool",
        ]:
            return {"tasks": [], "composite_task": None}
        nested_payload = request.metadata.get("payload")
        initial_payload = (
            dict(nested_payload)
            if isinstance(nested_payload, dict)
            else dict(request.metadata)
        )
        scheduler = self._scheduler()
        tasks = scheduler.enqueue_tool_chain(
            required_tools,
            initial_payload=initial_payload,
            title="Analyse des logs Néron",
            priority="high" if request.channel == "telegram" else "medium",
            metadata={
                "capability_request_id": request.request_id,
                "source_channel": request.channel,
                "user_id": request.user_id,
            },
        )
        composite = scheduler.enqueue_composite_task(
            title="Résultat de l’analyse des logs Néron",
            depends_on=[tasks[-1].task_id],
            priority="high" if request.channel == "telegram" else "medium",
            metadata={
                "capability_request_id": request.request_id,
                "source_channel": request.channel,
                "user_id": request.user_id,
                "chain_id": (
                    getattr(tasks[0], "metadata", {}) or {}
                ).get("chain_id"),
            },
        )
        scheduler.wake_worker()
        return {"tasks": tasks, "composite_task": composite}

    def _easter_date(self, year: int) -> date:
        a = year % 19
        b = year // 100
        c = year % 100
        d = b // 4
        e = b % 4
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i = c // 4
        k = c % 4
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        month = (h + l - 7 * m + 114) // 31
        day = ((h + l - 7 * m + 114) % 31) + 1
        return date(year, month, day)
