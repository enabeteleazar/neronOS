# tests/test_sessions.py
"""
Tests unitaires — Session & SessionStore
Couvre : CRUD, JSONL persistence, pruning, messages_for_llm, sanitization.
"""

import json
import pytest
from pathlib import Path
from modules.sessions import Session, SessionStore, MAX_HISTORY_TOKENS


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    return SessionStore(sessions_dir=tmp_path)


@pytest.fixture
def session():
    return Session(id="test-session", system_prompt="Tu es Néron.")


# ── Session : ajout de messages ────────────────────────────────────────────────

class TestSessionMessages:
    def test_add_user(self, session):
        session.add_user("bonjour")
        assert len(session.history) == 1
        assert session.history[0]["role"] == "user"
        assert session.history[0]["content"] == "bonjour"
        assert "ts" in session.history[0]

    def test_add_assistant(self, session):
        session.add_assistant("salut !")
        assert session.history[0]["role"] == "assistant"
        assert session.history[0]["content"] == "salut !"

    def test_add_tool_result(self, session):
        session.add_tool_result("tool-123", {"result": "ok"})
        msg = session.history[0]
        assert msg["role"] == "tool"
        assert msg["tool_use_id"] == "tool-123"
        assert json.loads(msg["content"]) == {"result": "ok"}

    def test_pending_intent_set_on_user(self, session):
        session.add_user("allume la lumière")
        assert session.pending_intent == "allume la lumière"

    def test_pending_intent_not_set_on_assistant(self, session):
        session.pending_intent = "initial"
        session.add_assistant("ok")
        assert session.pending_intent == "initial"

    def test_clear(self, session):
        session.add_user("a")
        session.add_assistant("b")
        session.clear()
        assert session.history == []


# ── Session : token estimation & pruning ───────────────────────────────────────

class TestSessionPruning:
    def test_estimated_tokens_empty(self, session):
        assert session.estimated_tokens() == len(session.system_prompt) // 4

    def test_estimated_tokens_with_messages(self, session):
        session.add_user("a" * 400)
        tokens = session.estimated_tokens()
        assert tokens > 100

    def test_no_prune_if_within_limit(self, session):
        session.add_user("court")
        pruned = session.prune_if_needed(max_tokens=MAX_HISTORY_TOKENS)
        assert pruned is False
        assert len(session.history) == 1

    def test_prune_removes_oldest(self, session):
        # Remplir l'historique jusqu'à dépasser le seuil
        for i in range(30):
            session.add_user("x" * 500)
            session.add_assistant("y" * 500)

        initial_len = len(session.history)
        pruned = session.prune_if_needed(max_tokens=100)
        assert pruned is True
        assert len(session.history) < initial_len

    def test_prune_never_leaves_orphan_tool(self, session):
        """Un tool_result en tête de liste est supprimé en premier."""
        session.history = [
            {"role": "tool", "tool_use_id": "x", "content": "r", "ts": 0},
            {"role": "assistant", "content": "ok", "ts": 1},
        ]
        # Forcer overflow
        session.system_prompt = "s" * (MAX_HISTORY_TOKENS * 4 + 1)
        session.prune_if_needed()
        if session.history:
            assert session.history[0]["role"] != "tool"


# ── Session : messages_for_llm ─────────────────────────────────────────────────

class TestMessagesForLLM:
    def test_strips_ts_from_user(self, session):
        session.add_user("bonjour")
        msgs = session.messages_for_llm()
        assert "ts" not in msgs[0]
        assert msgs[0] == {"role": "user", "content": "bonjour"}

    def test_strips_ts_from_assistant(self, session):
        session.add_assistant("salut")
        msgs = session.messages_for_llm()
        assert msgs[0] == {"role": "assistant", "content": "salut"}

    def test_tool_format(self, session):
        session.add_tool_result("tid", {"x": 1})
        msgs = session.messages_for_llm()
        assert msgs[0]["role"] == "tool"
        assert msgs[0]["tool_use_id"] == "tid"
        assert "ts" not in msgs[0]

    def test_full_conversation_order(self, session):
        session.add_user("q1")
        session.add_assistant("r1")
        session.add_user("q2")
        msgs = session.messages_for_llm()
        assert [m["role"] for m in msgs] == ["user", "assistant", "user"]


# ── SessionStore : CRUD ────────────────────────────────────────────────────────

class TestSessionStoreCRUD:
    def test_create_and_get(self, store):
        s = store.create("sess-1", system_prompt="Tu es test.")
        assert s.id == "sess-1"
        assert s.system_prompt == "Tu es test."
        got = store.get("sess-1")
        assert got is not None
        assert got.id == "sess-1"

    def test_get_missing_returns_none(self, store):
        assert store.get("inexistant") is None

    def test_get_or_create_creates(self, store):
        s = store.get_or_create("new-sess")
        assert s is not None
        assert s.id == "new-sess"

    def test_get_or_create_existing(self, store):
        s1 = store.create("existing")
        s2 = store.get_or_create("existing")
        assert s1.id == s2.id

    def test_delete_file_and_cache(self, store, tmp_path):
        store.create("del-me")
        result = store.delete("del-me")
        assert result is True
        assert store.get("del-me") is None
        assert not (tmp_path / "del-me.jsonl").exists()

    def test_delete_nonexistent_returns_false(self, store):
        assert store.delete("ghost") is False

    def test_list_ids(self, store):
        store.create("a")
        store.create("b")
        store.create("c")
        ids = store.list_ids()
        assert set(ids) == {"a", "b", "c"}


# ── SessionStore : persistance JSONL ──────────────────────────────────────────

class TestSessionStorePersistence:
    def test_save_and_reload(self, store, tmp_path):
        s = store.create("persist")
        s.add_user("hello")
        s.add_assistant("world")
        store.save(s)

        # Vider le cache pour forcer la lecture disque
        store._cache.clear()
        loaded = store.get("persist")
        assert loaded is not None
        assert len(loaded.history) == 2
        assert loaded.history[0]["content"] == "hello"
        assert loaded.history[1]["content"] == "world"

    def test_system_prompt_persisted(self, store):
        store.create("sp", system_prompt="Prompt personnalisé.")
        store._cache.clear()
        loaded = store.get("sp")
        assert loaded.system_prompt == "Prompt personnalisé."

    def test_metadata_persisted(self, store):
        store.create("meta", metadata={"source": "telegram"})
        store._cache.clear()
        loaded = store.get("meta")
        assert loaded.metadata == {"source": "telegram"}

    def test_append_msg(self, store, tmp_path):
        s = store.create("append")
        msg = {"role": "user", "content": "appended", "ts": 0}
        store.append_msg(s, msg)

        # Relire le fichier brut
        path = tmp_path / "append.jsonl"
        lines = path.read_text().splitlines()
        assert any("appended" in l for l in lines)

    def test_save_atomic_tmp_cleaned(self, store, tmp_path):
        s = store.create("atomic")
        store.save(s)
        tmp = tmp_path / "atomic.tmp"
        assert not tmp.exists()

    def test_invalid_jsonl_line_ignored(self, store, tmp_path):
        """Une ligne JSONL corrompue ne doit pas bloquer le chargement."""
        path = tmp_path / "corrupt.jsonl"
        path.write_text(
            json.dumps({"_type": "session_header", "id": "corrupt",
                        "system": "s", "metadata": {}}) + "\n"
            + "NOT_JSON\n"
            + json.dumps({"role": "user", "content": "ok", "ts": 0}) + "\n"
        )
        s = store.get("corrupt")
        assert s is not None
        assert len(s.history) == 1
        assert s.history[0]["content"] == "ok"


# ── SessionStore : sanitisation des IDs ───────────────────────────────────────

class TestSessionStoreSanitization:
    def test_path_strips_slashes(self, store, tmp_path):
        path = store._path("../../etc/passwd")
        # Le path doit rester dans sessions_dir (pas de traversal réel)
        assert path.parent == tmp_path
        # Le fichier ne doit pas pointer vers /etc/passwd
        assert str(path) != "/etc/passwd"
        assert path.suffix == ".jsonl"

    def test_path_allows_alphanumeric(self, store, tmp_path):
        path = store._path("session-abc_123.v2")
        assert path.suffix == ".jsonl"
        assert "session-abc_123.v2" in path.stem
