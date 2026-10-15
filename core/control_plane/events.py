# core/control_plane/events.py

from typing import Any, Callable

from core.infrastructure.event_bus import event_bus


class EventBus:
    """Synchronous compatibility facade over the canonical infrastructure Event Bus."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = {}

    def on(self, event: str, callback: Callable) -> None:
        handlers = self._handlers.setdefault(event, [])
        if callback in handlers:
            return
        handlers.append(callback)

    def emit(self, event: str, data: Any = None) -> None:
        event_bus.publish(
            event_type=event,
            source="control_plane",
            payload={"data": data},
        )
        for callback in list(self._handlers.get(event, [])):
            callback(data)
