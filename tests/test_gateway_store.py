from __future__ import annotations

from pathlib import Path

import pytest

from gateways.store import ConnectionStore


@pytest.fixture
def store(tmp_path: Path) -> ConnectionStore:
    return ConnectionStore(path=tmp_path / "gateways_connections.sqlite3")


def test_unknown_connector_defaults_to_not_configured(store: ConnectionStore):
    state = store.get_state("google")
    assert state.status == "not_configured"
    assert state.detail is None


def test_set_state_then_get_state_roundtrips(store: ConnectionStore):
    written = store.set_state("google", "connected")
    read = store.get_state("google")
    assert read.status == "connected"
    assert read.updated_at == written.updated_at


def test_set_state_overwrites_previous_state(store: ConnectionStore):
    store.set_state("google", "configured_disconnected", detail="pas encore connecte")
    store.set_state("google", "connected")
    state = store.get_state("google")
    assert state.status == "connected"
    assert state.detail is None


def test_list_states_only_returns_known_connectors(store: ConnectionStore):
    store.set_state("google", "connected")
    store.set_state("github", "error", detail="token expire")
    states = store.list_states()
    assert set(states) == {"google", "github"}
    assert states["github"].status == "error"


def test_store_persists_across_instances(tmp_path: Path):
    path = tmp_path / "gateways_connections.sqlite3"
    ConnectionStore(path=path).set_state("notion", "connected")
    reopened = ConnectionStore(path=path)
    assert reopened.get_state("notion").status == "connected"
