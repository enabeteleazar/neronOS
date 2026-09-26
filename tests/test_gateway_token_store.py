from __future__ import annotations

import stat
from pathlib import Path

from gateways.token_store import TokenStore


def test_unknown_connector_has_no_refresh_token(tmp_path: Path):
    store = TokenStore(path=tmp_path / "tokens.sqlite3")
    assert store.get_refresh_token("google") is None


def test_set_then_get_refresh_token_roundtrips(tmp_path: Path):
    store = TokenStore(path=tmp_path / "tokens.sqlite3")
    store.set_refresh_token("google", "rt-abc")
    assert store.get_refresh_token("google") == "rt-abc"


def test_set_refresh_token_overwrites_previous_value(tmp_path: Path):
    store = TokenStore(path=tmp_path / "tokens.sqlite3")
    store.set_refresh_token("google", "rt-old")
    store.set_refresh_token("google", "rt-new")
    assert store.get_refresh_token("google") == "rt-new"


def test_delete_removes_the_token(tmp_path: Path):
    store = TokenStore(path=tmp_path / "tokens.sqlite3")
    store.set_refresh_token("google", "rt-abc")
    store.delete("google")
    assert store.get_refresh_token("google") is None


def test_token_db_file_is_created_with_restrictive_permissions(tmp_path: Path):
    path = tmp_path / "tokens.sqlite3"
    TokenStore(path=path).set_refresh_token("google", "rt-abc")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_tokens_persist_across_instances(tmp_path: Path):
    path = tmp_path / "tokens.sqlite3"
    TokenStore(path=path).set_refresh_token("notion", "rt-notion")
    reopened = TokenStore(path=path)
    assert reopened.get_refresh_token("notion") == "rt-notion"
