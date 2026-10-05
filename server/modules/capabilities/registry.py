from __future__ import annotations

import json
import time
from collections.abc import Iterable
from typing import Any

from agents.factory.registry import DynamicAgentRegistry
from modules.capabilities.models import Capability
from modules.capabilities.router import normalize_text
try:
    from goal.projects.manager import ProjectManager, get_project_manager
except ImportError:  # goal absent (service séparé)
    from common.goal_unavailable import unavailable
    ProjectManager, get_project_manager = unavailable('ProjectManager', 'get_project_manager')

_GENERIC_RESPONSE_MARKERS = (
    "demande traitee",
    "agent disponible",
    "je suis un agent",
    "reponse deterministe",
)


class CapabilityRegistry:
    def __init__(
        self,
        *,
        agent_registry: DynamicAgentRegistry | None = None,
        project_manager: ProjectManager | None = None,
        builtins: Iterable[Capability] | None = None,
    ) -> None:
        self.agent_registry = agent_registry or DynamicAgentRegistry()
        self.project_manager = project_manager or get_project_manager()
        self._builtins = list(
            self._default_builtins() if builtins is None else builtins
        )
        self._generated: dict[str, Capability] = {}
        self._cache: list[Capability] | None = None
        self._cache_at = 0.0

    def list_capabilities(self) -> list[Capability]:
        if self._cache is not None and time.monotonic() - self._cache_at < 2.0:
            return list(self._cache)
        projects = self._completed_projects()
        capabilities = [
            *self._builtins,
            *self._agent_capabilities(projects),
            *self._project_capabilities(projects),
        ]
        known = {capability.slug for capability in capabilities}
        capabilities.extend(
            capability
            for slug, capability in self._generated.items()
            if slug not in known
        )
        self._cache = capabilities
        self._cache_at = time.monotonic()
        return list(capabilities)

    def find_matching_capability(self, text: str) -> Capability | None:
        return self._best_match(text, self.list_capabilities())

    def find_matching_tool(self, text: str) -> Capability | None:
        return self._best_match(
            text,
            (
                capability
                for capability in self.list_capabilities()
                if capability.capability_type == "tool"
            ),
        )

    def find_matching_agent(self, text: str) -> Capability | None:
        return self._best_match(
            text,
            (
                capability
                for capability in self.list_capabilities()
                if capability.capability_type == "agent"
            ),
        )

    def capability_exists(self, signature: str) -> bool:
        wanted = normalize_text(signature)
        return any(
            normalize_text(capability.signature or capability.slug) == wanted
            for capability in self.list_capabilities()
        )

    def register_generated_capability(
        self,
        *,
        slug: str,
        capability_type: str,
        source: str = "generated",
        name: str | None = None,
        description: str = "",
        aliases: list[str] | None = None,
        signature: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Capability:
        capability = Capability(
            slug=slug,
            name=name or slug,
            capability_type=capability_type,
            source=source,
            description=description,
            aliases=aliases or [],
            signature=signature,
            agent_slug=slug if capability_type == "agent" else None,
            tool_slug=slug if capability_type == "tool" else None,
            metadata=metadata or {},
        )
        self._generated[slug] = capability
        self._cache = None
        return capability

    def _agent_capabilities(
        self,
        projects: list[dict[str, Any]],
    ) -> list[Capability]:
        capabilities = []
        projects_by_agent = self._projects_by_agent(projects)
        for record in self.agent_registry.list_agent_records():
            spec = record.get("spec") if isinstance(record.get("spec"), dict) else {}
            searchable = str(record.get("match_text") or "")
            capability_type = self._agent_capability_type(spec, searchable)
            slug = str(record.get("module_name") or record.get("agent_name") or "")
            if not slug:
                continue
            project = projects_by_agent.get(slug)
            if project and not self._project_is_routable(project):
                continue
            aliases = self._spec_text_values(spec)
            capabilities.append(
                Capability(
                    slug=slug,
                    name=str(record.get("agent_name") or slug),
                    capability_type=capability_type,
                    source="runtime_agent" if capability_type == "agent" else "generated_tool",
                    description=str(spec.get("goal") or spec.get("title") or searchable),
                    aliases=aliases,
                    signature=str(record.get("spec_signature") or slug),
                    agent_slug=slug,
                    tool_slug=slug if capability_type == "tool" else None,
                    metadata={"spec": spec, "path": record.get("path")},
                )
            )
        return capabilities

    def _project_capabilities(
        self,
        projects: list[dict[str, Any]],
    ) -> list[Capability]:
        capabilities = []
        for project in projects:
            if not self._project_is_routable(project):
                continue
            metadata = project.get("metadata") or {}
            result = project.get("result") or {}
            slug = str(
                project.get("registered_agent")
                or result.get("agent")
                or metadata.get("agent_name")
                or ""
            )
            if not slug:
                continue
            creation_type = str(metadata.get("creation_type") or "agent")
            capability_type = "tool" if creation_type == "tool" else "agent"
            capabilities.append(
                Capability(
                    slug=slug,
                    name=str(project.get("title") or slug),
                    capability_type=capability_type,
                    source="project",
                    description=str(project.get("query") or project.get("title") or ""),
                    aliases=[str(project.get("query") or "")],
                    signature=str(metadata.get("capability_signature") or slug),
                    agent_slug=slug,
                    tool_slug=slug if capability_type == "tool" else None,
                    metadata={"project_id": project.get("project_id")},
                )
            )
        return capabilities

    def _completed_projects(self) -> list[dict[str, Any]]:
        try:
            return self.project_manager.list_projects(
                status="completed",
                limit=500,
            )
        except Exception:
            return []

    def _projects_by_agent(
        self,
        projects: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        for project in projects:
            metadata = project.get("metadata") or {}
            result = project.get("result") or {}
            slug = str(
                project.get("registered_agent")
                or result.get("agent")
                or metadata.get("agent_name")
                or ""
            )
            if slug:
                indexed.setdefault(slug, project)
        return indexed

    def _project_is_routable(self, project: dict[str, Any]) -> bool:
        metadata = project.get("metadata") or {}
        internal = bool(
            metadata.get("internal_capability_request")
            or metadata.get("capability_request_id")
        )
        if not internal:
            return True

        validation = project.get("business_validation_result") or {}
        scenario = validation.get("scenario") or {}
        context = validation.get("validation_context") or {}
        response = normalize_text(str(validation.get("actual_response") or ""))
        generic = any(marker in response for marker in _GENERIC_RESPONSE_MARKERS)
        return bool(
            validation.get("ok")
            and scenario.get("fallback") is False
            and context.get("internal_capability_request")
            and not generic
        )

    def _best_match(
        self,
        text: str,
        capabilities: Iterable[Capability],
    ) -> Capability | None:
        query = normalize_text(text)
        query_tokens = {token for token in query.split() if len(token) >= 3}
        best: tuple[float, Capability] | None = None
        for capability in capabilities:
            haystack = normalize_text(
                " ".join(
                    [
                        capability.slug,
                        capability.name,
                        capability.description,
                        *capability.aliases,
                        json.dumps(capability.metadata, ensure_ascii=False, sort_keys=True),
                    ]
                )
            )
            phrases = [
                normalize_text(value)
                for value in [capability.slug, capability.name, *capability.aliases]
                if value
            ]
            phrase_hit = any(phrase and phrase in query for phrase in phrases)
            tokens = {token for token in haystack.split() if len(token) >= 3}
            overlap = len(query_tokens & tokens) / max(1, len(query_tokens))
            score = max(overlap, 0.95 if phrase_hit else 0.0)
            if score >= 0.34 and (best is None or score > best[0]):
                best = (score, capability)
        return best[1] if best else None

    def _agent_capability_type(self, spec: dict[str, Any], searchable: str) -> str:
        normalized = normalize_text(
            " ".join(
                [
                    searchable,
                    str(spec.get("kind") or ""),
                    str(spec.get("goal") or ""),
                    " ".join(self._spec_text_values(spec)),
                ]
            )
        )
        durable = (
            "surveille",
            "monitor",
            "alerte",
            "periodique",
            "automatiquement",
            "chaque jour",
            "maintien",
            "suivi",
        )
        if str(spec.get("kind") or "").lower() == "tool":
            return "tool"
        return "agent" if any(token in normalized for token in durable) else "tool"

    def _spec_text_values(self, spec: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for key in ("capabilities", "aliases", "inputs", "outputs"):
            value = spec.get(key)
            if isinstance(value, list):
                values.extend(str(item) for item in value)
        for key in ("goal", "title", "name", "description"):
            if spec.get(key):
                values.append(str(spec[key]))
        return values

    def _default_builtins(self) -> list[Capability]:
        return [
            Capability(
                slug="date.easter",
                name="Date de Pâques",
                capability_type="tool",
                source="builtin_tool",
                description="Calculer la date de Pâques pour une année.",
                aliases=["date de paques", "paques"],
                signature="date.easter",
                tool_slug="date.easter",
            ),
            Capability(
                slug="date.current",
                name="Date courante",
                capability_type="tool",
                source="builtin_tool",
                description="Donner la date courante.",
                aliases=[
                    "donne moi la date",
                    "quelle date sommes nous",
                    "on est quel jour",
                    "quel jour sommes nous",
                ],
                signature="date.current",
                tool_slug="date.current",
            ),
            Capability(
                slug="date.christmas_countdown",
                name="Délai avant Noël",
                capability_type="tool",
                source="builtin_tool",
                description="Calculer le nombre de jours avant Noël.",
                aliases=["jours avant noel", "delai avant noel", "combien de jours avant noel"],
                signature="date.christmas_countdown",
                tool_slug="date.christmas_countdown",
            ),
            Capability(
                slug="network.subnet",
                name="Calcul de subnet",
                capability_type="tool",
                source="builtin_tool",
                description="Calculer les informations d'un réseau IPv4 ou IPv6 en CIDR.",
                aliases=["calcule le subnet", "subnet", "sous reseau"],
                signature="network.subnet",
                tool_slug="network.subnet",
            ),
            Capability(
                slug="system.diagnostic",
                name="Diagnostic système Néron",
                capability_type="tool",
                source="builtin_tool",
                description="Produire un diagnostic ponctuel de Néron et de la machine.",
                aliases=["diagnostic de neron", "diagnostic systeme"],
                signature="system.diagnostic",
                tool_slug="system.diagnostic",
            ),
        ]
