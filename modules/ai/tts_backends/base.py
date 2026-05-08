from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class TTSBackend(ABC):
    @abstractmethod
    def generate(self, text: str, output_path: Path, *, voice: str, rate: str, volume: str) -> None:
        raise NotImplementedError
