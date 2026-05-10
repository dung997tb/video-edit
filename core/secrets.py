from __future__ import annotations

import threading
from collections.abc import Mapping


class InMemorySecretStore:
    """Best-effort per-process secret handoff for embedded/local workers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, dict[str, str]] = {}

    def put(self, job_id: str, secrets: Mapping[str, str]) -> None:
        if not secrets:
            return
        with self._lock:
            current = dict(self._items.get(job_id, {}))
            current.update({str(key): str(value) for key, value in secrets.items()})
            self._items[job_id] = current

    def get(self, job_id: str, path: str | None = None) -> str | dict[str, str] | None:
        with self._lock:
            secrets = dict(self._items.get(job_id, {}))
        if path is None:
            return secrets
        return secrets.get(path)

    def discard(self, job_id: str) -> None:
        with self._lock:
            self._items.pop(job_id, None)
