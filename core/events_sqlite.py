from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from core.events import Event


class SQLiteEventBus:
    def __init__(self, db_path: str | Path) -> None:
        self._db = Path(db_path)
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._subscribers: dict[str, list[Callable[[Event], None]]] = {}
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(type)")

    def publish(self, event_type: str, payload: dict) -> Event:
        event = Event(type=event_type, payload=payload)
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "INSERT INTO events(type, payload, created_at) VALUES (?, ?, ?)",
                (event.type, json.dumps(event.payload), event.created_at.isoformat()),
            )
        for handler in self._subscribers.get(event_type, []) + self._subscribers.get("*", []):
            handler(event)
        return event

    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    def recent(self, *, event_type: str | None = None, limit: int = 100) -> list[Event]:
        limit = max(1, int(limit))
        if event_type is None:
            query = "SELECT type, payload, created_at FROM events ORDER BY id DESC LIMIT ?"
            params = (limit,)
        else:
            query = "SELECT type, payload, created_at FROM events WHERE type = ? ORDER BY id DESC LIMIT ?"
            params = (event_type, limit)
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute(query, params).fetchall()
        events = [_row_to_event(row) for row in rows]
        return list(reversed(events))


def _row_to_event(row: tuple) -> Event:
    return Event(
        type=row[0],
        payload=dict(json.loads(row[1] or "{}")),
        created_at=datetime.fromisoformat(row[2]),
    )
