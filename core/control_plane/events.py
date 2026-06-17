# core/control_plane/events.py

import inspect
from typing import Any, Callable

from modules.events.event import Event
from modules.events.event_bus import event_bus


class EventBus:
    """Synchronous compatibility facade over the canonical Event Bus."""

    def __init__(self) -> None:
        self._wrappers: dict[tuple[str, Callable], Callable] = {}

    def on(self, event: str, callback: Callable) -> None:
        key = (event, callback)
        if key in self._wrappers:
            return

        async def wrapper(message: Event) -> None:
            value = message.payload.get("data")
            result = callback(value)
            if inspect.isawaitable(result):
                await result

        self._wrappers[key] = wrapper
        event_bus.subscribe(event, wrapper)

    def emit(self, event: str, data: Any = None) -> None:
        event_bus.publish_background(Event(
            type=event,
            source="control_plane",
            payload={"data": data},
        ))
