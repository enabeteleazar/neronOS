from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from threading import RLock
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HealthState:
    """Tracks process lifetime and builds the canonical Core health payloads."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.mark_started()

    def mark_started(self) -> None:
        with self._lock:
            self._started_monotonic = time.monotonic()
            self._started_at = _utc_now()

    @property
    def uptime(self) -> float:
        with self._lock:
            started = self._started_monotonic
        return round(max(0.0, time.monotonic() - started), 3)

    def health(self, version: str) -> dict[str, Any]:
        with self._lock:
            started_at = self._started_at.isoformat()
        return {
            "service": "core",
            "status": "healthy",
            "version": version,
            "uptime": self.uptime,
            "started_at": started_at,
            "timestamp": _utc_now().isoformat(),
        }

    def status(
        self,
        version: str,
        dependencies: dict[str, Any] | None = None,
        registry: dict[str, Any] | None = None,
        event_bus: dict[str, Any] | None = None,
        providers: dict[str, Any] | None = None,
        a2a: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "service": "core",
            "status": "ok",
            "version": version,
            "pid": os.getpid(),
            "uptime": self.uptime,
            "dependencies": dependencies or {},
            "registry": registry or {},
            "event_bus": event_bus or {},
            "providers": providers or {},
            "a2a": a2a or {},
        }


health_state = HealthState()
