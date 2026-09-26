"""Etat de connexion par connecteur, persiste en sqlite.

Ne stocke jamais de secret : seulement le statut (`not_configured`,
`configured_disconnected`, `connected`, `error`) et un detail texte. Les
identifiants eux-memes restent dans secrets.env, jamais dans cette base.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from common.paths import NERON_DATA_DIR
from gateways.models import ConnectionStatus, ConnectorState

DB_PATH = NERON_DATA_DIR / "gateways_connections.sqlite3"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _db(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _init_db(path: Path) -> None:
    with _db(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS connection_state (
                connector_id TEXT PRIMARY KEY,
                status       TEXT NOT NULL,
                detail       TEXT,
                updated_at   TEXT NOT NULL
            )
            """
        )
        conn.commit()


class ConnectionStore:
    def __init__(self, path: Path = DB_PATH) -> None:
        self._path = path
        _init_db(path)

    def get_state(self, connector_id: str) -> ConnectorState:
        with _db(self._path) as conn:
            row = conn.execute(
                "SELECT * FROM connection_state WHERE connector_id = ?",
                (connector_id,),
            ).fetchone()
        if row is None:
            return ConnectorState(
                connector_id=connector_id,
                status="not_configured",
                detail=None,
                updated_at=_now(),
            )
        return ConnectorState(
            connector_id=row["connector_id"],
            status=row["status"],
            detail=row["detail"],
            updated_at=row["updated_at"],
        )

    def set_state(
        self,
        connector_id: str,
        status: ConnectionStatus,
        detail: str | None = None,
    ) -> ConnectorState:
        updated_at = _now()
        with _db(self._path) as conn:
            conn.execute(
                """
                INSERT INTO connection_state (connector_id, status, detail, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(connector_id) DO UPDATE SET
                    status = excluded.status,
                    detail = excluded.detail,
                    updated_at = excluded.updated_at
                """,
                (connector_id, status, detail, updated_at),
            )
            conn.commit()
        return ConnectorState(
            connector_id=connector_id,
            status=status,
            detail=detail,
            updated_at=updated_at,
        )

    def list_states(self) -> dict[str, ConnectorState]:
        with _db(self._path) as conn:
            rows = conn.execute("SELECT * FROM connection_state").fetchall()
        return {
            row["connector_id"]: ConnectorState(
                connector_id=row["connector_id"],
                status=row["status"],
                detail=row["detail"],
                updated_at=row["updated_at"],
            )
            for row in rows
        }
