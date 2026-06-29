from __future__ import annotations

import re
from typing import Any

from agents.builtin.base_agent import get_logger
from core.a2a import A2AClient, AgentCard, AgentMessage, AgentTask, a2a_client
from core.providers.models import ProviderRequest
from core.providers.registry import ProviderRegistry, provider_registry

from .agent_registry import AgentRegistry, agent_registry
from .agent_factory import AgentCreationRequest, AgentFactory, agent_factory
from .execution_loop import GoalExecutionLoop
from .models import (
    GoalAnalysis,
    GoalEngineResult,
    GoalExecutionResult,
    GoalPlan,
    GoalRequest,
    GoalVerificationResult,
)

logger = get_logger("core.goal_engine")


class GoalEngine:
    """Phase 3.1 foundation Goal Engine.

    This class deliberately does not create real agents yet. It only analyzes a
    goal, checks for an A2A-compatible agent, prepares a foundation execution,
    verifies the outcome, and records the run through the Memory Provider.
    """

    def __init__(
        self,
        *,
        providers: ProviderRegistry = provider_registry,
        a2a: A2AClient = a2a_client,
        agents: AgentRegistry = agent_registry,
        factory: AgentFactory = agent_factory,
        execution_loop: GoalExecutionLoop | None = None,
    ) -> None:
        self.providers = providers
        self.a2a = a2a
        self.agents = agents
        self.factory = factory
        self.execution_loop = execution_loop or GoalExecutionLoop()

    async def execute(self, goal_request: GoalRequest) -> GoalEngineResult:
        analysis = await self.analyze(goal_request)
        agent = self.find_agent(analysis)
        creation_plan = None
        creation_artifacts = None
        generation_error = None
        generation_attempted = False
        if agent is None and self._supervised_creation_allowed(analysis):
            generation_attempted = True
            creation = self.factory.create_plan(
                AgentCreationRequest(goal_analysis=analysis)
            )
            creation_plan = creation.model_dump(mode="json")
            try:
                artifacts = self.factory.existing_candidate(creation)
                if artifacts is None:
                    artifacts = await self.factory.generate_supervised(creation, self.providers)
                try:
                    artifacts = await self.factory.validate_artifacts(artifacts)
                except RuntimeError as first_error:
                    artifacts = await self.factory.repair_supervised(
                        artifacts,
                        creation,
                        self.providers,
                        str(first_error),
                    )
                    artifacts = await self.factory.validate_artifacts(artifacts)
                artifacts = self.factory.promote(artifacts)
                creation_artifacts = artifacts.model_dump(mode="json")
                agent = self._reload_generated_agent(analysis, creation.spec.name)
                if agent is None:
                    raise RuntimeError("generated agent was not discovered after registry reload")
                creation_plan["files_created"] = True
                creation_plan["runtime_registered"] = True
            except Exception as exc:
                generation_error = str(exc)
        plan = self.build_plan(analysis, agent)
        if agent is not None and creation_plan is not None:
            plan.objective = str(
                creation_plan["spec"].get("validation_task")
                or plan.objective
            )
        loop_result = None
        if plan.agent_creation_required:
            execution = await self.execute_plan(plan)
            verification = self.verify(execution)
        else:
            loop_result = await self.execution_loop.run(
                execute=lambda _iteration: self.execute_plan(plan),
                verify=self.verify,
                fix=self.fix,
            )
            execution = loop_result.result
            verification = loop_result.verification
        memory_learned = await self.learn(execution)
        if execution.agent_creation_required and creation_plan is None:
            creation_plan = self.factory.create_plan(
                AgentCreationRequest(goal_analysis=analysis)
            ).model_dump(mode="json")

        status = (
            "completed"
            if loop_result is not None and loop_result.status == "completed"
            else "blocked"
            if loop_result is not None and loop_result.status == "blocked"
            else execution.status
        )
        response = self._response_text(execution, verification)
        return GoalEngineResult(
            goal_id=goal_request.goal_id,
            goal_status=status,
            analysis=analysis,
            plan=plan,
            execution=execution,
            verification=verification,
            response=response,
            agent_found=execution.agent_found,
            agent_creation_required=execution.agent_creation_required,
            memory_learned=memory_learned,
            llm_used=analysis.llm_used or generation_attempted,
            a2a_used=execution.a2a_used,
            agent_creation_plan=creation_plan,
            loop_iterations=loop_result.iterations if loop_result else 0,
            next_action=(
                loop_result.next_action
                if loop_result
                else "Créer ou enregistrer un agent compatible."
                if execution.agent_creation_required
                else None
            ),
            metadata={
                "goal_engine_phase": "first_real_goal",
                "provider_memory_used": memory_learned,
                "agent_creation_artifacts": creation_artifacts,
                "agent_generation_error": generation_error,
            },
        )

    async def analyze(self, goal_request: GoalRequest) -> GoalAnalysis:
        objective = goal_request.objective.strip()
        normalized = _normalize(objective)
        capabilities = _capabilities_for_goal(normalized)
        complexity = _complexity(objective)
        return GoalAnalysis(
            goal_id=goal_request.goal_id,
            objective=objective,
            summary=objective,
            required_capabilities=capabilities,
            complexity=complexity,
            llm_used=False,
            metadata={
                "analysis_mode": "rule_based_foundation",
                "source": goal_request.source,
            },
        )

    def find_agent(self, goal_analysis: GoalAnalysis) -> AgentCard | None:
        self.agents.load_existing_agents()
        agent = self.agents.find_for_goal(goal_analysis)
        if agent is not None and self.a2a.get_agent(agent.agent_id) is None:
            if agent.metadata.get("source") == "agent_runtime":
                from agents.runtime.runtime import get_agent_runtime
                from .runtime_adapter import register_runtime_handler

                register_runtime_handler(
                    agent,
                    self.a2a,
                    self.providers,
                    get_agent_runtime(),
                )
            else:
                self.a2a.register_agent(agent)
        return agent

    def _reload_generated_agent(
        self,
        analysis: GoalAnalysis,
        expected_agent_id: str,
    ) -> AgentCard | None:
        from agents.runtime.runtime import get_agent_runtime
        from .runtime_adapter import register_runtime_handler

        runtime = get_agent_runtime()
        runtime.reload()
        self.agents.load_existing_agents(runtime)
        card = self.agents.get(expected_agent_id) or self.agents.find_for_goal(analysis)
        if card is not None:
            register_runtime_handler(card, self.a2a, self.providers, runtime)
        return card

    @staticmethod
    def _supervised_creation_allowed(analysis: GoalAnalysis) -> bool:
        required = set(analysis.required_capabilities)
        return "agent_creation" in required and "weather" in required

    def build_plan(
        self,
        goal_analysis: GoalAnalysis,
        agent: AgentCard | None = None,
    ) -> GoalPlan:
        if agent is None:
            return GoalPlan(
                goal_id=goal_analysis.goal_id,
                objective=goal_analysis.objective,
                status="agent_creation_required",
                analysis=goal_analysis,
                steps=[
                    "Analyser l'objectif.",
                    "Identifier les capacités requises.",
                    "Créer ou enregistrer un agent compatible avant exécution.",
                ],
                agent_found=False,
                agent_creation_required=True,
                metadata={"plan_mode": "foundation_no_agent"},
            )

        return GoalPlan(
            goal_id=goal_analysis.goal_id,
            objective=goal_analysis.objective,
            status="agent_found",
            analysis=goal_analysis,
            steps=[
                "Analyser l'objectif.",
                "Préparer une tâche A2A pour l'agent compatible.",
                "Attendre l'acceptation de l'agent.",
            ],
            agent_id=agent.agent_id,
            agent_found=True,
            agent_creation_required=False,
            metadata={"plan_mode": "foundation_a2a_prepare"},
        )

    async def execute_plan(self, goal_plan: GoalPlan) -> GoalExecutionResult:
        if goal_plan.agent_creation_required or not goal_plan.agent_id:
            return GoalExecutionResult(
                goal_id=goal_plan.goal_id,
                status="agent_creation_required",
                plan=goal_plan,
                agent_found=False,
                agent_creation_required=True,
                a2a_used=False,
                result={
                    "message": "Aucun agent compatible n'est enregistré.",
                    "required_capabilities": goal_plan.analysis.required_capabilities,
                },
            )

        task = AgentTask(
            target_agent=goal_plan.agent_id,
            messages=[
                AgentMessage(
                    role="user",
                    content=goal_plan.objective,
                    metadata={
                        "goal_id": goal_plan.goal_id,
                        "source": "goal_engine_foundation",
                    },
                )
            ],
            payload={
                "goal_id": goal_plan.goal_id,
                "objective": goal_plan.objective,
                "required_capabilities": goal_plan.analysis.required_capabilities,
                "foundation_mode": True,
            },
        )
        response = await self.a2a.send_task(task)
        goal_plan.a2a_task_id = response.task_id
        status = "execution_prepared" if response.status in {"accepted", "completed"} else "failed"
        return GoalExecutionResult(
            goal_id=goal_plan.goal_id,
            status=status,
            plan=goal_plan,
            agent_found=True,
            agent_creation_required=False,
            a2a_used=True,
            a2a_response=response,
            result=response.result,
            error=response.error,
        )

    def verify(self, goal_result: GoalExecutionResult) -> GoalVerificationResult:
        if goal_result.status == "agent_creation_required":
            return GoalVerificationResult(
                goal_id=goal_result.goal_id,
                status="pending",
                ok=True,
                reason="Exécution en attente : création ou enregistrement d'agent requis.",
            )

        if goal_result.status == "execution_prepared":
            return GoalVerificationResult(
                goal_id=goal_result.goal_id,
                status="verified",
                ok=True,
                reason="La tâche A2A a été préparée et acceptée.",
            )

        return GoalVerificationResult(
            goal_id=goal_result.goal_id,
            status="failed",
            ok=False,
            reason=goal_result.error or "Échec de préparation de l'exécution.",
        )

    async def fix(
        self,
        _goal_result: GoalExecutionResult,
        _verification: GoalVerificationResult,
        _iteration: int,
    ) -> None:
        """Foundation replan hook. It deliberately performs no mutation."""
        return None

    async def learn(self, goal_result: GoalExecutionResult) -> bool:
        providers = self.providers.by_type("memory")
        provider_info = providers[0] if providers else None
        provider = self.providers.get(provider_info.name) if provider_info else None
        if provider is None:
            logger.info("goal_engine_memory_provider_unavailable goal_id=%s", goal_result.goal_id)
            return False

        response = await provider.execute(
            ProviderRequest(
                action="remember",
                payload={
                    "content": self._memory_content(goal_result),
                    "category": "goal",
                    "metadata": {
                        "goal_id": goal_result.goal_id,
                        "goal_status": goal_result.status,
                        "agent_found": goal_result.agent_found,
                        "agent_creation_required": goal_result.agent_creation_required,
                    },
                },
            )
        )
        return response.error is None

    def status(self) -> dict[str, Any]:
        return {
            "status": "available",
            "phase": "3.5_a2a_agent",
            "agent_registry": self.agents.status(),
            "providers": self.providers.status(),
            "a2a": self.a2a.status(),
        }

    @staticmethod
    def _memory_content(goal_result: GoalExecutionResult) -> str:
        return (
            f"Goal Engine execution {goal_result.goal_id}: "
            f"status={goal_result.status}, "
            f"agent_found={goal_result.agent_found}, "
            f"agent_creation_required={goal_result.agent_creation_required}."
        )

    @staticmethod
    def _response_text(
        execution: GoalExecutionResult,
        verification: GoalVerificationResult,
    ) -> str:
        if execution.agent_creation_required:
            capabilities = ", ".join(execution.plan.analysis.required_capabilities) or "generic"
            return (
                "Objectif analysé. Aucun agent compatible n'est actuellement enregistré. "
                f"Statut : agent_creation_required. Capacités requises : {capabilities}."
            )

        if execution.status == "execution_prepared":
            agent_result = (
                execution.a2a_response.result.get("agent_response")
                if execution.a2a_response is not None
                else None
            )
            if agent_result:
                return f"{agent_result} Vérification : {verification.status}."
            return (
                "Objectif analysé. Un agent compatible a été trouvé et la tâche A2A "
                f"a été exécutée. Vérification : {verification.status}."
            )

        return f"Objectif analysé, mais la préparation a échoué : {execution.error or verification.reason}"


def _normalize(text: str) -> str:
    normalized = text.lower()
    normalized = normalized.replace("’", "'").replace("-", " ")
    return " ".join(normalized.split())


def _complexity(text: str) -> str:
    words = len(text.split())
    if words >= 35:
        return "complex"
    if words >= 12:
        return "medium"
    return "simple"


def _capabilities_for_goal(normalized: str) -> list[str]:
    capabilities: set[str] = set()
    capability_rules = {
        "monitoring": ("surveille", "monitor", "etat", "état", "alerte", "watchdog"),
        "service_supervision": ("service", "systemd", "daemon", "neron"),
        "home_automation": ("home assistant", "lumiere", "lumière", "thermostat"),
        "memory": ("memoire", "mémoire", "souvenir", "obsidian", "sqlite"),
        "text_generation": ("resume", "résume", "redige", "rédige", "explique"),
        "planning": ("plan", "organise", "objectif"),
        "agent_creation": ("cree un agent", "crée un agent", "creer un agent", "créer un agent"),
        "weather": ("meteo", "météo", "weather"),
        "forecast": ("prevision", "prévision", "forecast", "meteo", "météo"),
    }
    for capability, tokens in capability_rules.items():
        if any(token in normalized for token in tokens):
            capabilities.add(capability)

    if not capabilities:
        words = re.findall(r"[a-zA-Z0-9_]+", normalized)
        capabilities.update(word for word in words if len(word) > 5)

    return sorted(capabilities or {"generic"})


from .builtin_agents import install_builtin_agents

install_builtin_agents(agent_registry, a2a_client)
goal_engine = GoalEngine()
