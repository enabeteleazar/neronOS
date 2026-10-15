from __future__ import annotations

from threading import RLock
from typing import Any, Iterable
import unicodedata

from core.a2a import AgentCard

from .models import GoalAnalysis


class AgentRegistry:
    """In-memory foundation registry for A2A-compatible agents."""

    def __init__(self, runtime: Any | None = None) -> None:
        self._lock = RLock()
        self._agents: dict[str, AgentCard] = {}
        self._runtime = runtime

    def register(self, agent_card: AgentCard) -> AgentCard:
        with self._lock:
            self._agents[agent_card.agent_id] = agent_card
        return agent_card

    def get(self, agent_id: str) -> AgentCard | None:
        with self._lock:
            return self._agents.get(agent_id)

    def list(self) -> list[AgentCard]:
        with self._lock:
            return list(self._agents.values())

    def find_by_capability(self, capability: str) -> list[AgentCard]:
        wanted = capability.strip().lower()
        with self._lock:
            return [
                agent
                for agent in self._agents.values()
                if agent.status == "available"
                and wanted in {item.lower() for item in agent.capabilities}
            ]

    def find_for_goal(self, goal_analysis: GoalAnalysis) -> AgentCard | None:
        objective = str(getattr(goal_analysis, "objective", ""))
        objective_tokens = _tokens(objective)
        required = {_normalize(item) for item in goal_analysis.required_capabilities}
        ranked: list[tuple[int, str, AgentCard]] = []
        for agent in self.list():
            if agent.status != "available":
                continue
            capabilities = {_normalize(item) for item in agent.capabilities}
            searchable = _tokens(
                " ".join(
                    [agent.agent_id, agent.name, agent.description, *agent.tags, *agent.capabilities]
                )
            )
            score = (
                len(required & capabilities) * 10
                + len(objective_tokens & searchable) * 2
                + int(bool(objective) and _normalize(agent.name) in _normalize(objective)) * 5
            )
            if score:
                ranked.append((score, agent.agent_id, agent))
        if not ranked:
            return None
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return ranked[0][2]

    def load_existing_agents(self, runtime: Any | None = None) -> list[AgentCard]:
        source = runtime or self._runtime
        if source is None:
            try:
                from agents.runtime.runtime import get_agent_runtime

                source = get_agent_runtime()
            except (ImportError, RuntimeError):
                return []
        registry = getattr(source, "registry", source)
        records = registry.list_agent_records()
        cards = [self.card_from_runtime_record(record) for record in records]
        for card in cards:
            self.register(card)
        return cards

    @staticmethod
    def card_from_runtime_record(record: dict[str, Any]) -> AgentCard:
        spec = record.get("spec") if isinstance(record.get("spec"), dict) else {}
        name = str(record.get("agent_name") or record.get("module_name") or "").strip()
        if not name:
            raise ValueError("runtime agent record has no name")
        return AgentCard(
            agent_id=str(record.get("module_name") or name),
            name=name,
            capabilities=_string_list(
                spec.get("capabilities")
                or spec.get("skills")
                or spec.get("required_capabilities")
            ),
            description=str(
                spec.get("description")
                or spec.get("purpose")
                or spec.get("goal")
                or record.get("match_text")
                or ""
            ),
            tags=_string_list(spec.get("tags")),
            status="available",
            metadata={
                "source": "agent_runtime",
                "path": str(record.get("path") or ""),
                "spec_signature": str(record.get("spec_signature") or ""),
            },
        )

    def status(self) -> dict[str, object]:
        agents = self.list()
        return {
            "count": len(agents),
            "available_count": len([agent for agent in agents if agent.status == "available"]),
            "agents": [agent.model_dump(mode="json") for agent in agents],
        }

    def clear(self) -> None:
        with self._lock:
            self._agents.clear()


agent_registry = AgentRegistry()


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value).lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join("".join(char if char.isalnum() else " " for char in text).split())


def _tokens(value: str) -> set[str]:
    stopwords = {
        "agent", "utilise", "utiliser", "cree", "creer", "pour", "avec",
        "dans", "une", "des", "les", "the",
    }
    return {
        token
        for token in _normalize(value).split()
        if len(token) > 2 and token not in stopwords
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, Iterable) or isinstance(value, (dict, bytes)):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
