from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
import sys
from threading import RLock
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Event(BaseModel):
    """Validated internal event contract."""

    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: UUID = Field(default_factory=uuid4)
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str
    type: str
    target: str | None = None
    payload: dict[str, Any]
    level: Literal["info", "warning", "error"] = EventLevel.INFO.value

    @field_validator("source", "type", "trace_id")
    @classmethod
    def require_non_empty_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value

    @field_validator("target")
    @classmethod
    def reject_empty_target(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("target must not be empty")
        return value

    @field_validator("timestamp")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("timestamp must be UTC")
        return value


class EventBus:
    """Small, process-local event journal for Core infrastructure events."""

    def __init__(self, max_events: int = 1_000, *, test_mode: bool = False) -> None:
        if max_events < 1:
            raise ValueError("max_events must be greater than zero")
        self._events: deque[Event] = deque(maxlen=max_events)
        self._lock = RLock()
        self._test_mode = test_mode

    def publish(
        self,
        event_type: str,
        source: str,
        payload: dict[str, Any] | None = None,
        target: str | None = None,
        trace_id: str | None = None,
        level: Literal["info", "warning", "error"] = "info",
    ) -> dict[str, Any]:
        if payload is not None and not isinstance(payload, dict):
            raise TypeError("payload must be a dictionary")

        event = Event(
            type=event_type,
            source=source,
            target=target,
            payload=deepcopy(payload) if payload is not None else {},
            trace_id=trace_id if trace_id is not None else str(uuid4()),
            level=level,
        )
        with self._lock:
            self._events.append(event)
        return self._serialize(event)

    def get_events(
        self,
        limit: int = 100,
        event_type: str | None = None,
        source: str | None = None,
        target: str | None = None,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if limit < 0:
            raise ValueError("limit cannot be negative")
        with self._lock:
            events = [
                event
                for event in self._events
                if (event_type is None or event.type == event_type)
                and (source is None or event.source == source)
                and (target is None or event.target == target)
                and (trace_id is None or event.trace_id == trace_id)
            ]
            events = events[-limit:] if limit else []
        return [self._serialize(event) for event in events]

    def clear(self) -> None:
        if not self._test_mode:
            raise RuntimeError("event bus can only be cleared in test mode")
        with self._lock:
            self._events.clear()

    def status(self) -> dict[str, Any]:
        with self._lock:
            count = len(self._events)
            latest = (
                self._events[-1].timestamp.isoformat()
                if self._events
                else None
            )
        return {"event_count": count, "latest_event_at": latest}

    @staticmethod
    def _serialize(event: Event) -> dict[str, Any]:
        return deepcopy(event.model_dump(mode="json"))


event_bus = EventBus(test_mode="pytest" in sys.modules)
