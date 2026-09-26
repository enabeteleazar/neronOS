from __future__ import annotations

import pytest

from gateways.registry import ConnectorRegistry


@pytest.fixture
def registry() -> ConnectorRegistry:
    return ConnectorRegistry()


def test_registry_loads_all_declared_connectors(registry: ConnectorRegistry):
    ids = {c.id for c in registry.list_connectors()}
    assert ids == {"google", "microsoft", "apple", "github", "notion"}


def test_get_returns_none_for_unknown_connector(registry: ConnectorRegistry):
    assert registry.get("does-not-exist") is None


def test_get_returns_the_matching_connector(registry: ConnectorRegistry):
    connector = registry.get("google")
    assert connector is not None
    assert connector.name == "Google"
    assert "mail" in connector.domains


@pytest.mark.parametrize(
    ("domain", "expected_ids"),
    [
        ("mail", {"google", "microsoft"}),
        ("reminders", {"google", "microsoft"}),
        ("calendar", {"google", "microsoft", "apple"}),
        ("repos", {"github"}),
        ("docs", {"notion"}),
        ("does-not-exist", set()),
    ],
)
def test_find_by_domain(registry: ConnectorRegistry, domain: str, expected_ids: set[str]):
    found = {c.id for c in registry.find_by_domain(domain)}
    assert found == expected_ids


def test_apple_does_not_cover_reminders_or_notes(registry: ConnectorRegistry):
    apple = registry.get("apple")
    assert apple is not None
    assert "reminders" not in apple.domains
    assert "notes" not in apple.domains


def test_no_secret_field_on_connector_model(registry: ConnectorRegistry):
    """Le registre ne doit jamais porter de secret : seulement des NOMS de
    variables d'environnement a lire depuis secrets.env."""
    for connector in registry.list_connectors():
        for env_name in connector.credential_env:
            assert env_name.isupper()
            assert env_name.startswith("NERON_GATEWAY_")
