from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, UTC
from typing import Any, Callable


@dataclass(slots=True)
class Event:
    type: str
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data


class InMemoryEventBus:
    def __init__(self) -> None:
        self._events: list[Event] = []
        self._subscribers: dict[str, list[Callable[[Event], None]]] = {}

    def publish(self, event_type: str, payload: dict[str, Any]) -> Event:
        event = Event(type=event_type, payload=payload)
        self._events.append(event)
        for handler in self._subscribers.get(event_type, []) + self._subscribers.get("*", []):
            handler(event)
        return event

    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    def recent(self, *, event_type: str | None = None, limit: int = 100) -> list[Event]:
        events = [event for event in self._events if event_type is None or event.type == event_type]
        return events[-limit:]
