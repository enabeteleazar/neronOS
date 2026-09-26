from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import uuid4


CapabilityExecutor = Callable[[str], Awaitable[Any]]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CapabilityRequest:
    text: str
    source: str = "user"
    channel: str = "api"
    request_id: str = field(default_factory=lambda: f"cap_{uuid4().hex}")
    user_id: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilityDecision:
    decision: str
    confidence: float
    reason: str
    capability_type: str | None = None
    selected_tool: str | None = None
    selected_agent: str | None = None
    requires_creation: bool = False
    creation_type: str | None = None
    async_required: bool = False
    human_validation_required: bool = False
    safety_level: str = "low"
    gateway_connector_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilityResult:
    status: str
    response: str
    async_started: bool = False
    goal_id: str | None = None
    project_id: str | None = None
    agent_slug: str | None = None
    tool_slug: str | None = None
    error: str | None = None
    request_id: str | None = None
    decision: CapabilityDecision | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.decision is not None:
            payload["decision"] = self.decision.to_dict()
        return payload


@dataclass
class Capability:
    slug: str
    name: str
    capability_type: str
    source: str
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    signature: str = ""
    agent_slug: str | None = None
    tool_slug: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    executor: CapabilityExecutor | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("executor", None)
        return payload


@dataclass
class RuleMatch:
    domain: str
    confidence: float
    matched_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DomainClassification:
    domain: str
    confidence: float
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Intent:
    action: str
    confidence: float
    durable: bool = False
    requested_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IntentUnderstanding:
    domain: DomainClassification
    intent: Intent
    provider: str = "rules"

    @property
    def confidence(self) -> float:
        return round((self.domain.confidence + self.intent.confidence) / 2, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain.to_dict(),
            "intent": self.intent.to_dict(),
            "provider": self.provider,
            "confidence": self.confidence,
        }


@dataclass
class CapabilityMatch:
    capability: Capability
    score: float
    domain_score: float
    intent_score: float
    lexical_score: float
    missing_tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability.to_dict(),
            "score": self.score,
            "domain_score": self.domain_score,
            "intent_score": self.intent_score,
            "lexical_score": self.lexical_score,
            "missing_tools": self.missing_tools,
        }


@dataclass
class ResolverAnalysis:
    text: str
    domain: DomainClassification
    intent: Intent
    decision: str
    confidence: float
    matched_agent: str | None = None
    matched_tool: str | None = None
    match_score: float | None = None
    missing_tools: list[str] = field(default_factory=list)
    provider: str = "rules"
    reason: str = ""
    gateway_connector_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "domain": self.domain.domain,
            "intent": self.intent.action,
            "confidence": self.confidence,
            "domain_confidence": self.domain.confidence,
            "intent_confidence": self.intent.confidence,
            "durable": self.intent.durable,
            "matched_agent": self.matched_agent,
            "matched_tool": self.matched_tool,
            "match_score": self.match_score,
            "missing_tools": self.missing_tools,
            "decision": self.decision,
            "provider": self.provider,
            "reason": self.reason,
            "evidence": self.domain.evidence,
            "gateway_connector_id": self.gateway_connector_id,
        }
