from __future__ import annotations

import threading
import time
from collections import defaultdict


class InMemoryRateLimiter:
    def __init__(self, requests_per_minute: int = 60) -> None:
        self._limit = max(0, int(requests_per_minute))
        self._lock = threading.Lock()
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        if self._limit <= 0:
            return True
        now = time.time()
        window_start = now - 60
        with self._lock:
            bucket = [timestamp for timestamp in self._buckets[key] if timestamp > window_start]
            if len(bucket) >= self._limit:
                self._buckets[key] = bucket
                return False
            bucket.append(now)
            self._buckets[key] = bucket
            return True
