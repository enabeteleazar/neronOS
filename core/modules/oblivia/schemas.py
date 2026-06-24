from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

MemorySource = Literal["sqlite", "obsidian", "memory_manager"]

MemoryCategory = Literal[
    "self",
    "project",
    "agent",
    "goal",
    "decision",
    "lesson",
    "runtime",
    "unknown",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source: MemorySource = "memory_manager"
    category: MemoryCategory = "unknown"
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_utc)
    updated_at: str = Field(default_factory=now_utc)


class MemoryQuery(BaseModel):
    query: str
    category: MemoryCategory | None = None
    limit: int = 10


class MemorySearchResult(BaseModel):
    record: MemoryRecord
    score: float = 1.0
    backend: str


class MemoryStatus(BaseModel):
    ok: bool
    sqlite: dict[str, Any]
    obsidian: dict[str, Any]
