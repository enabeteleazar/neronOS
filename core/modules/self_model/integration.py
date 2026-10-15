from __future__ import annotations

from typing import Any

from core.infrastructure.event_bus import event_bus


def emit_memory_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Publish memory lifecycle events without coupling Oblivia to SelfModel."""
    return event_bus.publish(
        event_type=event_type,
        source="memory.oblivia",
        payload=payload,
        target="self_model",
    )
