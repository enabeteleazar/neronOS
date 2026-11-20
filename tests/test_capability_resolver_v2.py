from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from modules.capabilities.domain_classifier import DomainClassifier
from modules.capabilities.intent_extractor import IntentExtractor
from modules.capabilities.intent_provider import RuleBasedIntentProvider
from modules.capabilities.matcher import CapabilityMatcher
from modules.capabilities.models import Capability
from modules.capabilities.registry import CapabilityRegistry
from modules.capabilities.resolver import CapabilityResolver
from tools.registry import ToolRegistry


class EmptyAgentRegistry:
    def list_agent_records(self):
        return []


class EmptyProjectManager:
    def list_projects(self, status=None, limit=100):
        return []


def make_registry(*capabilities: Capability) -> CapabilityRegistry:
    return CapabilityRegistry(
        agent_registry=EmptyAgentRegistry(),
        project_manager=EmptyProjectManager(),
        builtins=capabilities,
    )


def agent(
    slug: str,
    domain_description: str,
    *,
    tools: list[str] | None = None,
) -> Capability:
    return Capability(
        slug=slug,
        name=slug,
        capability_type="agent",
        source="runtime_agent",
        description=domain_description,
        aliases=[domain_description],
        agent_slug=slug,
        metadata={"spec": {"tools": tools or []}},
    )


@pytest.mark.parametrize(
    ("text", "domain"),
    [
        ("Analyse les logs Néron", "logs"),
        ("Analyse les sauvegardes Néron", "backups"),
        ("Analyse les bases SQLite", "sqlite"),
        ("Vérifie les services systemd", "systemd"),
        ("Donne la date de Pâques", "easter"),
        ("Combien de jours avant Noël ?", "christmas"),
        ("Calcule le subnet 192.168.1.0/24", "subnet"),
        ("Quelle météo demain ?", "weather"),
        ("Ajoute ceci à mon agenda", "agenda"),
        ("Ouvre mon calendrier", "calendar"),
        ("Montre mes mails", "mail"),
        ("Ouvre ma boîte de réception", "mail"),
        ("Montre mes contacts", "contacts"),
        ("Cherche dans mon carnet d'adresses", "contacts"),
        ("Montre mes notes", "notes"),
        ("Montre mes rappels", "reminders"),
        ("Liste mes rappels Google", "reminders"),
        ("Ouvre mon repo", "repos"),
        ("Montre la pull request", "repos"),
        ("Ouvre ma page Notion", "docs"),
    ],
)
def test_domain_classifier(text: str, domain: str):
    result = DomainClassifier().classify(text)

    assert result.domain == domain
    assert result.confidence >= 0.9


@pytest.mark.parametrize(
    ("text", "action"),
    [
        ("Analyse les logs", "analyse"),
        ("Résume les erreurs", "resume"),
        ("Fais un diagnostic", "diagnostic"),
        ("Surveille le serveur", "surveillance"),
        ("Calcule le subnet", "calcul"),
        ("Crée un agent", "creation"),
        ("Recherche les sauvegardes", "recherche"),
        ("Compare les bases", "comparaison"),
        ("Préviens-moi en cas d'erreur", "notification"),
    ],
)
def test_intent_extractor(text: str, action: str):
    result = IntentExtractor().extract(text)

    assert result.action == action
    assert result.confidence >= 0.9


def test_matcher_keeps_logs_and_backups_separate(tmp_path):
    log_agent = agent(
        "logs_agent",
        "Analyse automatiquement les logs Néron et résume les erreurs",
    )
    backup_agent = agent(
        "backup_agent",
        "Analyse automatiquement les sauvegardes et backups Néron",
    )
    provider = RuleBasedIntentProvider()
    matcher = CapabilityMatcher(
        tool_registry=ToolRegistry(tmp_path / "tools.json")
    )

    log_scores = matcher.score_capabilities(
        "Analyse les logs Néron",
        provider.classify_sync("Analyse les logs Néron"),
        [log_agent, backup_agent],
    )
    backup_scores = matcher.score_capabilities(
        "Analyse les sauvegardes Néron",
        provider.classify_sync("Analyse les sauvegardes Néron"),
        [log_agent, backup_agent],
    )

    assert log_scores[0].capability.slug == "logs_agent"
    assert log_scores[0].score >= 0.8
    assert next(
        score.score for score in log_scores
        if score.capability.slug == "backup_agent"
    ) <= 0.18
    assert backup_scores[0].capability.slug == "backup_agent"
    assert backup_scores[0].score >= 0.8
    assert next(
        score.score for score in backup_scores
        if score.capability.slug == "logs_agent"
    ) <= 0.18


def test_backup_request_without_backup_agent_creates_agent(tmp_path):
    resolver = CapabilityResolver(
        registry=make_registry(
            agent(
                "logs_agent",
                "Analyse automatiquement les logs Néron",
            )
        ),
        matcher=CapabilityMatcher(
            tool_registry=ToolRegistry(tmp_path / "tools.json")
        ),
    )

    analysis = resolver.analyze("Analyse les sauvegardes Néron")

    assert analysis.domain.domain == "backups"
    assert analysis.intent.action == "analyse"
    assert analysis.matched_agent is None
    assert analysis.decision == "create_agent"


def test_log_request_selects_log_agent_not_backup_agent(tmp_path):
    resolver = CapabilityResolver(
        registry=make_registry(
            agent(
                "backup_agent",
                "Analyse automatiquement les sauvegardes Néron",
            ),
            agent(
                "logs_agent",
                "Analyse automatiquement les logs Néron",
            ),
        ),
        matcher=CapabilityMatcher(
            tool_registry=ToolRegistry(tmp_path / "tools.json")
        ),
    )

    logs = resolver.analyze("Analyse les logs Néron")
    backups = resolver.analyze("Analyse les sauvegardes Néron")

    assert logs.decision == "execute_agent"
    assert logs.matched_agent == "logs_agent"
    assert backups.decision == "execute_agent"
    assert backups.matched_agent == "backup_agent"


def test_existing_agent_with_missing_tool_requests_tool_creation(tmp_path):
    resolver = CapabilityResolver(
        registry=make_registry(
            agent(
                "backup_agent",
                "Analyse automatiquement les sauvegardes Néron",
                tools=["backup_reader_tool"],
            )
        ),
        matcher=CapabilityMatcher(
            tool_registry=ToolRegistry(tmp_path / "tools.json")
        ),
    )

    analysis = resolver.analyze("Analyse les sauvegardes Néron")

    assert analysis.matched_agent == "backup_agent"
    assert analysis.missing_tools == ["backup_reader_tool"]
    assert analysis.decision == "create_tool"


@pytest.mark.asyncio
async def test_future_intent_provider_contract_is_async():
    result = await RuleBasedIntentProvider().classify(
        "Analyse les bases SQLite Néron"
    )

    assert result.domain.domain == "sqlite"
    assert result.intent.action == "analyse"


@pytest.mark.asyncio
async def test_capability_analyze_api(monkeypatch, tmp_path):
    from modules.capabilities import routes

    resolver = CapabilityResolver(
        registry=make_registry(),
        matcher=CapabilityMatcher(
            tool_registry=ToolRegistry(tmp_path / "tools.json")
        ),
    )
    monkeypatch.setattr(routes, "get_capability_resolver", lambda: resolver)
    app = FastAPI()
    app.include_router(routes.router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-api-key"},
    ) as client:
        response = await client.post(
            "/capabilities/analyze",
            json={"text": "Analyse les sauvegardes Néron"},
        )

    assert response.status_code == 200
    assert response.json()["domain"] == "backups"
    assert response.json()["intent"] == "analyse"
    assert response.json()["matched_agent"] is None
    assert response.json()["decision"] == "create_agent"
