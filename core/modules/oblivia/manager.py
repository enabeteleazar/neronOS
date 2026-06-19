from __future__ import annotations

from .schemas import (
    MemoryQuery,
    MemoryRecord,
    MemorySearchResult,
    MemoryStatus,
)
from .sqlite_adapter import SQLiteMemoryAdapter
from .obsidian_adapter import ObsidianMemoryAdapter
from .semantic.semantic_search import ObsidianSemanticSearch
from .text_utils import normalize_text


class ObliviaMemoryManager:
    def __init__(
        self,
        sqlite_path: str | None = None,
        obsidian_path: str | None = None,
    ):
        self.sqlite = (
            SQLiteMemoryAdapter(sqlite_path)
            if sqlite_path
            else SQLiteMemoryAdapter()
        )
        self.obsidian = (
            ObsidianMemoryAdapter(obsidian_path)
            if obsidian_path
            else ObsidianMemoryAdapter()
        )
        self.semantic = ObsidianSemanticSearch(str(self.obsidian.vault))

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
        normalized_query = normalize_text(query)

        for row in self.sqlite.search(normalized_query, limit):
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
            for item in self.obsidian.search(normalized_query, remaining):
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

        existing_paths = {
            item.record.metadata.get("path")
            for item in results
            if isinstance(item.record.metadata, dict)
        }

        try:
            for item in self.semantic.search(normalized_query, limit=limit):
                path = item.get("path")
                if path in existing_paths:
                    continue

                record = MemoryRecord(
                    source="obsidian",
                    category="project",
                    content=item.get("preview", ""),
                    metadata={
                        "path": path,
                        "title": item.get("title"),
                        "folder": item.get("folder"),
                        "search": "semantic",
                    },
                )

                results.append(
                    MemorySearchResult(
                        record=record,
                        backend="obsidian_semantic",
                        score=float(item.get("score") or 0.0),
                    )
                )
        except Exception:
            pass

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
