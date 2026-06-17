from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


DB_PATH = Path("/etc/neron/data/memory/memory.db")
DEFAULT_TZ = "Europe/Paris"


def now_iso() -> str:
    return datetime.now(ZoneInfo(DEFAULT_TZ)).isoformat()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'user',
            confidence REAL NOT NULL DEFAULT 1.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_value ON memories(value)")
    conn.commit()


def save_memory(
    *,
    category: str,
    key: str,
    value: str,
    source: str = "user",
    confidence: float = 1.0,
) -> dict:
    timestamp = now_iso()

    with connect() as conn:
        existing = conn.execute(
            """
            SELECT * FROM memories
            WHERE category = ? AND key = ? AND value = ?
            LIMIT 1
            """,
            (category, key, value),
        ).fetchone()

        if existing is not None:
            return dict(existing)

        cur = conn.execute(
            """
            INSERT INTO memories(category, key, value, source, confidence, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (category, key, value, source, confidence, timestamp, timestamp),
        )
        conn.commit()
        memory_id = cur.lastrowid

    return {
        "id": memory_id,
        "category": category,
        "key": key,
        "value": value,
        "source": source,
        "confidence": confidence,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def search_memories(query: str | None = None, *, limit: int = 10) -> list[dict]:
    with connect() as conn:
        if query:
            like = f"%{query}%"
            rows = conn.execute(
                """
                SELECT * FROM memories
                WHERE key LIKE ? OR value LIKE ? OR category LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM memories
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    return [dict(row) for row in rows]
