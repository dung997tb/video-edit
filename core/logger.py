from __future__ import annotations

import logging
import sys
from pathlib import Path

try:
    from loguru import logger
except ImportError:  # pragma: no cover - fallback for minimal local environments
    class _FallbackLogger:
        def __init__(self) -> None:
            self._logger = logging.getLogger("ai-video-engine")
            self._logger.setLevel(logging.INFO)
            self._logger.propagate = False

        def remove(self) -> None:
            self._logger.handlers.clear()

        def add(self, sink, level: str = "INFO", **_: object) -> None:
            handler = logging.StreamHandler(sink) if hasattr(sink, "write") else logging.FileHandler(sink)
            handler.setLevel(getattr(logging, level.upper(), logging.INFO))
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self._logger.addHandler(handler)

        def info(self, message: str, *args: object) -> None:
            self._logger.info(message.format(*args))

        def warning(self, message: str, *args: object) -> None:
            self._logger.warning(message.format(*args))

        def error(self, message: str, *args: object) -> None:
            self._logger.error(message.format(*args))

        def exception(self, message: str, *args: object) -> None:
            self._logger.exception(message.format(*args))

    logger = _FallbackLogger()


def configure_logger(logs_dir: Path, level: str = "INFO") -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stdout, level=level, enqueue=True, backtrace=False, diagnose=False)
    logger.add(
        logs_dir / "app.log",
        level=level,
        rotation="10 MB",
        retention="10 days",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )


__all__ = ["configure_logger", "logger"]
