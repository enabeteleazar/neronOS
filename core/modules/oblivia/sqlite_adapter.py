from __future__ import annotations

import sqlite3
from pathlib import Path

from .schemas import MemoryRecord
from .text_utils import normalize_text

DEFAULT_DB = "/etc/neron/server/memory/neron_memory.db"


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
                normalized_content TEXT,
                metadata TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """)
            self._migrate_schema(conn)
            conn.commit()

    def _migrate_schema(self, conn):
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(memory_records)")
        }

        if "normalized_content" not in columns:
            conn.execute(
                "ALTER TABLE memory_records ADD COLUMN normalized_content TEXT"
            )

        rows = conn.execute(
            """
            SELECT id, content
            FROM memory_records
            WHERE normalized_content IS NULL OR normalized_content = ''
            """
        ).fetchall()

        for record_id, content in rows:
            conn.execute(
                """
                UPDATE memory_records
                SET normalized_content = ?
                WHERE id = ?
                """,
                (normalize_text(content), record_id),
            )

    def add(self, record: MemoryRecord):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_records(
                    id,
                    source,
                    category,
                    content,
                    normalized_content,
                    metadata,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.source,
                    record.category,
                    record.content,
                    normalize_text(record.content),
                    str(record.metadata),
                    record.created_at,
                    record.updated_at,
                ),
            )
            conn.commit()

    def search(self, query: str, limit: int = 10):
        normalized_query = normalize_text(query)

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, source, category, content
                FROM memory_records
                WHERE normalized_content LIKE ?
                LIMIT ?
                """,
                (f"%{normalized_query}%", limit),
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
