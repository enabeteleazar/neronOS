from __future__ import annotations

import logging
import time
from dataclasses import dataclass, asdict
from typing import Any

from modules.events.event import Event

logger = logging.getLogger("neron.runtime.governor")


@dataclass
class RuntimePolicy:
    runtime_mode: str = "normal"
    planner_enabled: bool = True
    heavy_reasoning_allowed: bool = True
    autonomous_actions_allowed: bool = True
    max_parallel_agents: int = 3
    preferred_llm_profile: str = "default"
    updated_at: float = 0.0
    source_event: str | None = None
    reason: str | None = None
    probable_cause: str | None = None
    evidence: list[str] | None = None


class RuntimeGovernor:
    def __init__(self) -> None:
        self.policy = RuntimePolicy(updated_at=time.time())

    def update_from_cognitive_state(
        self,
        cognitive_state: dict[str, Any],
        source_event: str | None = None,
    ) -> dict[str, Any]:
        runtime_mode = cognitive_state.get("runtime_mode", "normal")
        primary_issue = cognitive_state.get("primary_issue")
        probable_cause = cognitive_state.get("probable_cause")
        evidence = cognitive_state.get("evidence", []) or []
        severity_score = cognitive_state.get("severity_score", 0) or 0

        if runtime_mode == "survival":
            policy = RuntimePolicy(
                runtime_mode="survival",
                planner_enabled=False,
                heavy_reasoning_allowed=False,
                autonomous_actions_allowed=False,
                max_parallel_agents=1,
                preferred_llm_profile="minimal",
                updated_at=time.time(),
                source_event=source_event,
                reason=primary_issue or "survival_mode",
                probable_cause=probable_cause,
                evidence=evidence,
            )

        elif runtime_mode == "degraded":
            policy = RuntimePolicy(
                runtime_mode="degraded",
                planner_enabled=True,
                heavy_reasoning_allowed=False,
                autonomous_actions_allowed=True,
                max_parallel_agents=1,
                preferred_llm_profile="light",
                updated_at=time.time(),
                source_event=source_event,
                reason=primary_issue or "degraded_mode",
                probable_cause=probable_cause,
                evidence=evidence,
            )

        elif runtime_mode == "prudent":
            policy = RuntimePolicy(
                runtime_mode="prudent",
                planner_enabled=True,
                heavy_reasoning_allowed=False,
                autonomous_actions_allowed=True,
                max_parallel_agents=1,
                preferred_llm_profile="balanced",
                updated_at=time.time(),
                source_event=source_event,
                reason=primary_issue or "runtime_pressure",
                probable_cause=probable_cause,
                evidence=evidence,
            )

        else:
            policy = RuntimePolicy(
                runtime_mode="normal",
                planner_enabled=True,
                heavy_reasoning_allowed=True,
                autonomous_actions_allowed=True,
                max_parallel_agents=3,
                preferred_llm_profile="default",
                updated_at=time.time(),
                source_event=source_event,
                reason=primary_issue,
                probable_cause=probable_cause,
                evidence=evidence,
            )

        if probable_cause == "voice_pipeline_cpu_pressure":
            policy.preferred_llm_profile = "minimal"
            policy.max_parallel_agents = 1

        elif probable_cause == "agent_or_llm_runtime_pressure":
            policy.preferred_llm_profile = "light"
            policy.max_parallel_agents = 1

        if severity_score >= 85:
            policy.runtime_mode = "survival"
            policy.planner_enabled = False
            policy.heavy_reasoning_allowed = False
            policy.autonomous_actions_allowed = False
            policy.max_parallel_agents = 1
            policy.preferred_llm_profile = "minimal"

        self.policy = policy

        logger.info(
            "runtime_policy_updated mode=%s planner=%s heavy_reasoning=%s autonomous=%s max_agents=%s llm_profile=%s reason=%s cause=%s",
            policy.runtime_mode,
            policy.planner_enabled,
            policy.heavy_reasoning_allowed,
            policy.autonomous_actions_allowed,
            policy.max_parallel_agents,
            policy.preferred_llm_profile,
            policy.reason,
            policy.probable_cause,
        )

        return self.to_dict()

    async def handle_self_model_event(self, event: Event) -> None:
        if event.type != "self_model.runtime_mode_changed":
            logger.info(
                "runtime_governor_ignored_event type=%s",
                event.type,
            )
            return

        payload = event.payload or {}

        cognitive_state = {
            "runtime_mode": payload.get("to"),
            "primary_issue": payload.get("primary_issue"),
            "severity_score": payload.get("severity_score"),
            "probable_cause": payload.get("probable_cause"),
            "evidence": payload.get("evidence", []),
        }

        self.update_from_cognitive_state(
            cognitive_state,
            source_event=event.type,
        )


    def authorize_system_command(
        self,
        *,
        actor: str,
        command: list[str],
        reason: str | None = None,
    ) -> bool:
        command_name = command[0] if command else ""

        # Toujours bloquer en survival
        if self.policy.runtime_mode == "survival":
            logger.warning(
                "system_command_denied actor=%s command=%s reason=%s runtime_mode=%s",
                actor,
                command,
                reason,
                self.policy.runtime_mode,
            )
            return False

        # Commandes de lecture autorisées
        read_only_commands = {
            "systemctl",
            "ss",
            "journalctl",
            "ps",
            "df",
            "free",
            "uptime",
        }

        if command_name not in read_only_commands:
            logger.warning(
                "system_command_denied actor=%s command=%s reason=%s cause=command_not_allowed",
                actor,
                command,
                reason,
            )
            return False

        # systemctl uniquement en lecture
        if command_name == "systemctl":
            allowed_systemctl_actions = {
                "status",
                "list-units",
                "is-active",
                "is-enabled",
            }

            action = command[1] if len(command) > 1 else ""

            if action not in allowed_systemctl_actions:
                logger.warning(
                    "systemctl_action_denied actor=%s action=%s command=%s reason=%s",
                    actor,
                    action,
                    command,
                    reason,
                )
                return False

        logger.info(
            "system_command_allowed actor=%s command=%s reason=%s runtime_mode=%s",
            actor,
            command,
            reason,
            self.policy.runtime_mode,
        )
        return True

    def authorize_agent_promotion(
        self,
        *,
        agent_name: str,
        requested_by: str = "system",
    ) -> bool:
        allowed = (
            self.policy.runtime_mode != "survival"
            and self.policy.autonomous_actions_allowed
        )
        log = logger.info if allowed else logger.warning
        log(
            "agent_promotion_%s agent=%s requested_by=%s runtime_mode=%s autonomous=%s reason=%s",
            "allowed" if allowed else "denied",
            agent_name,
            requested_by,
            self.policy.runtime_mode,
            self.policy.autonomous_actions_allowed,
            self.policy.reason,
        )
        return allowed

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.policy)


_governor: RuntimeGovernor | None = None


def get_runtime_governor() -> RuntimeGovernor:
    global _governor

    if _governor is None:
        _governor = RuntimeGovernor()

    return _governor


async def handle_self_model_governor_event(event: Event) -> None:
    governor = get_runtime_governor()
    await governor.handle_self_model_event(event)
