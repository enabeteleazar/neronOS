from __future__ import annotations

import sqlite3
from pathlib import Path

from .schemas import MemoryRecord

DEFAULT_DB = "/etc/neron/memory/neron_memory.db"


class SQLiteMemoryAdapter:
    def __init__(self, db_path: str = DEFAULT_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_records(
                id TEXT PRIMARY KEY,
                source TEXT,
                category TEXT,
                content TEXT,
                metadata TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """)
            conn.commit()

    def add(self, record: MemoryRecord):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_records
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.source,
                    record.category,
                    record.content,
                    str(record.metadata),
                    record.created_at,
                    record.updated_at,
                ),
            )
            conn.commit()

    def search(self, query: str, limit: int = 10):
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, source, category, content
                FROM memory_records
                WHERE content LIKE ?
                LIMIT ?
                """,
                (f"%{query}%", limit),
            ).fetchall()

        return rows

    def status(self):
        with self._connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM memory_records"
            ).fetchone()[0]

        return {
            "backend": "sqlite",
            "path": str(self.db_path),
            "records": count,
        }
