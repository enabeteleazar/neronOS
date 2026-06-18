from __future__ import annotations

from .schemas import (
    MemoryQuery,
    MemoryRecord,
    MemorySearchResult,
    MemoryStatus,
)
from .sqlite_adapter import SQLiteMemoryAdapter
from .obsidian_adapter import ObsidianMemoryAdapter


class ObliviaMemoryManager:
    def __init__(self):
        self.sqlite = SQLiteMemoryAdapter()
        self.obsidian = ObsidianMemoryAdapter()

    def remember(self, record: MemoryRecord) -> MemoryRecord:
        self.sqlite.add(record)

        if record.category in {
            "self",
            "project",
            "decision",
            "lesson",
            "agent",
        }:
            self.obsidian.add(record)

        return record

    def search(self, query: str, limit: int = 10):
        results = []

        for row in self.sqlite.search(query, limit):
            record = MemoryRecord(
                id=row[0],
                source=row[1],
                category=row[2],
                content=row[3],
            )

            results.append(
                MemorySearchResult(
                    record=record,
                    backend="sqlite",
                    score=1.0,
                )
            )

        remaining = max(0, limit - len(results))

        if remaining > 0:
            for item in self.obsidian.search(query, remaining):
                record = MemoryRecord(
                    source="obsidian",
                    category="project",
                    content=item["content"],
                    metadata={"path": item["path"]},
                )

                results.append(
                    MemorySearchResult(
                        record=record,
                        backend="obsidian",
                        score=item["score"],
                    )
                )

        return sorted(results, key=lambda item: item.score, reverse=True)

    def recall(self, query: MemoryQuery):
        return self.search(
            query.query,
            query.limit,
        )

    def status(self):
        return MemoryStatus(
            ok=True,
            sqlite=self.sqlite.status(),
            obsidian=self.obsidian.status(),
        )
