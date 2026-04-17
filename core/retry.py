from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from core.exceptions import JobCancelledError

T = TypeVar("T")


def execute_with_retry(
    fn: Callable[[], T],
    attempts: int,
    delay_seconds: float,
    retryable: tuple[type[BaseException], ...] = (Exception,),
    non_retryable: tuple[type[BaseException], ...] = (JobCancelledError,),
) -> T:
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retryable as exc:  # type: ignore[misc]
            if isinstance(exc, non_retryable):
                raise
            last_error = exc
            if attempt >= attempts:
                raise
            time.sleep(delay_seconds * (2 ** (attempt - 1)))
    if last_error:
        raise last_error
    raise RuntimeError("retry loop exited unexpectedly")
