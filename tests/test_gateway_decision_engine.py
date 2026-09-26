from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.capabilities.decision_engine import DecisionEngine
from modules.capabilities.domain_classifier import DomainClassifier
from modules.capabilities.intent_extractor import IntentExtractor
from modules.capabilities.models import IntentUnderstanding


def _understanding(text: str) -> IntentUnderstanding:
    return IntentUnderstanding(
        domain=DomainClassifier().classify(text),
        intent=IntentExtractor().extract(text),
    )


def _connector(connector_id: str, name: str = "Google", connect_hint: str = "hint"):
    return SimpleNamespace(id=connector_id, name=name, connect_hint=connect_hint)


def _state(status: str):
    return SimpleNamespace(status=status)


def test_connected_gateway_wins_over_tool_creation():
    lookup_calls = []

    def lookup(domain: str):
        lookup_calls.append(domain)
        return [(_connector("google"), _state("connected"))]

    engine = DecisionEngine(gateway_lookup=lookup)
    decision, confidence, reason, extra = engine.decide(
        "Montre mes mails", _understanding("Montre mes mails"), None
    )

    assert decision == "use_gateway"
    assert extra == {"gateway_connector_id": "google"}
    assert confidence > 0
    assert lookup_calls == ["mail"]


def test_gateway_covered_but_not_connected_proposes_connection():
    def lookup(domain: str):
        return [(_connector("github"), _state("configured_disconnected"))]

    engine = DecisionEngine(gateway_lookup=lookup)
    decision, _confidence, _reason, extra = engine.decide(
        "Montre la pull request", _understanding("Montre la pull request"), None
    )

    assert decision == "propose_gateway_connection"
    assert extra == {"gateway_connector_id": "github"}


def test_gateway_domain_with_no_connector_says_no_gateway_available():
    def lookup(domain: str):
        return []

    engine = DecisionEngine(gateway_lookup=lookup)
    decision, _confidence, _reason, extra = engine.decide(
        "Montre mes notes", _understanding("Montre mes notes"), None
    )

    assert decision == "no_gateway_available"
    assert extra == {}


def test_first_connected_connector_wins_when_several_cover_the_domain():
    def lookup(domain: str):
        return [
            (_connector("microsoft"), _state("configured_disconnected")),
            (_connector("google"), _state("connected")),
        ]

    engine = DecisionEngine(gateway_lookup=lookup)
    decision, _confidence, _reason, extra = engine.decide(
        "Montre mes mails", _understanding("Montre mes mails"), None
    )

    assert decision == "use_gateway"
    assert extra == {"gateway_connector_id": "google"}


@pytest.mark.parametrize("text", ["Quelle météo demain ?", "Calcule le subnet 192.168.1.0/24"])
def test_non_gateway_domains_never_call_the_gateway_lookup(text: str):
    lookup_calls = []

    def lookup(domain: str):
        lookup_calls.append(domain)
        return []

    engine = DecisionEngine(gateway_lookup=lookup)
    decision, _confidence, _reason, _extra = engine.decide(
        text, _understanding(text), None
    )

    assert lookup_calls == []
    assert decision == "create_tool"


def test_durable_gateway_domain_request_still_creates_an_agent():
    """Une demande de surveillance durable reste geree par le Goal Engine,
    meme sur un domaine couvert par une passerelle : le gateway repond a une
    question ponctuelle, pas a une surveillance en continu (hors scope de
    cette increment)."""

    def lookup(domain: str):
        raise AssertionError("le lookup ne doit pas etre appele pour une demande durable")

    engine = DecisionEngine(gateway_lookup=lookup)
    text = "Surveille mes mails et préviens-moi"
    decision, _confidence, _reason, extra = engine.decide(
        text, _understanding(text), None
    )

    assert decision == "create_agent"
    assert extra == {}
