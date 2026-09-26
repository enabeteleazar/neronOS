"""Stockage des refresh tokens OAuth obtenus dynamiquement (device flow).

Fichier DELIBEREMENT separe de `store.ConnectionStore`, qui documente ne
jamais porter de secret : c'est ici, et seulement ici, que vit un secret
genere a l'issue d'un flux OAuth (par opposition aux identifiants statiques
que l'utilisateur pose lui-meme dans secrets.env). Cree en mode 0600, comme
secrets.env.
"""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from common.paths import NERON_DATA_DIR

TOKENS_DB_PATH = NERON_DATA_DIR / "gateways_tokens.sqlite3"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _db(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
    if is_new and path.exists():
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _init_db(path: Path) -> None:
    with _db(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                connector_id  TEXT PRIMARY KEY,
                refresh_token TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
            """
        )
        conn.commit()


class TokenStore:
    def __init__(self, path: Path = TOKENS_DB_PATH) -> None:
        self._path = path
        _init_db(path)

    def get_refresh_token(self, connector_id: str) -> str | None:
        with _db(self._path) as conn:
            row = conn.execute(
                "SELECT refresh_token FROM oauth_tokens WHERE connector_id = ?",
                (connector_id,),
            ).fetchone()
        return row["refresh_token"] if row else None

    def set_refresh_token(self, connector_id: str, refresh_token: str) -> None:
        with _db(self._path) as conn:
            conn.execute(
                """
                INSERT INTO oauth_tokens (connector_id, refresh_token, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(connector_id) DO UPDATE SET
                    refresh_token = excluded.refresh_token,
                    updated_at = excluded.updated_at
                """,
                (connector_id, refresh_token, _now()),
            )
            conn.commit()

    def delete(self, connector_id: str) -> None:
        with _db(self._path) as conn:
            conn.execute("DELETE FROM oauth_tokens WHERE connector_id = ?", (connector_id,))
            conn.commit()
