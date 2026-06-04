from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any


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

    def copy(self, source_job_id: str, target_job_id: str) -> None:
        with self._lock:
            secrets = dict(self._items.get(source_job_id, {}))
            if secrets:
                self._items[target_job_id] = secrets


class SupabaseSecretStore:
    """Persistent per-job secret handoff for Supabase-backed workers."""

    def __init__(self, client: Any, table: str = "job_secrets") -> None:
        self.client = client
        self.table = table

    def put(self, job_id: str, secrets: Mapping[str, str]) -> None:
        rows = [
            {"job_id": str(job_id), "path": str(path), "value": str(value)}
            for path, value in secrets.items()
        ]
        if rows:
            self.client.table(self.table).upsert(rows).execute()

    def get(self, job_id: str, path: str | None = None) -> str | dict[str, str] | None:
        query = self.client.table(self.table).select("path,value").eq("job_id", str(job_id))
        if path is not None:
            query = query.eq("path", str(path)).limit(1)
        response = query.execute()
        rows = response.data or []
        if path is not None:
            return str(rows[0]["value"]) if rows else None
        return {str(row["path"]): str(row["value"]) for row in rows}

    def discard(self, job_id: str) -> None:
        self.client.table(self.table).delete().eq("job_id", str(job_id)).execute()

    def copy(self, source_job_id: str, target_job_id: str) -> None:
        secrets = self.get(source_job_id)
        if isinstance(secrets, dict) and secrets:
            self.put(target_job_id, secrets)
