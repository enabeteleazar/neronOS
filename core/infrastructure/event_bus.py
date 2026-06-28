from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventBus:
    """Small, process-local event journal for Core infrastructure events."""

    def __init__(self, max_events: int = 1_000) -> None:
        if max_events < 1:
            raise ValueError("max_events must be greater than zero")
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._lock = RLock()

    def publish(
        self,
        event_type: str,
        source: str,
        payload: dict[str, Any] | None = None,
        target: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        if not event_type.strip():
            raise ValueError("event_type is required")
        if not source.strip():
            raise ValueError("source is required")
        if payload is not None and not isinstance(payload, dict):
            raise TypeError("payload must be a dictionary")

        event = {
            "event_id": str(uuid4()),
            "type": event_type,
            "source": source,
            "target": target,
            "payload": deepcopy(payload) if payload is not None else {},
            "trace_id": trace_id or str(uuid4()),
            "timestamp": _utc_now(),
        }
        with self._lock:
            self._events.append(event)
        return deepcopy(event)

    def get_events(self, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 0:
            raise ValueError("limit cannot be negative")
        with self._lock:
            events = list(self._events)[-limit:] if limit else []
        return deepcopy(events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def status(self) -> dict[str, Any]:
        with self._lock:
            count = len(self._events)
            latest = self._events[-1]["timestamp"] if self._events else None
        return {"event_count": count, "latest_event_at": latest}


event_bus = EventBus()
