from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.models import JobRecord


class PipelineOrchestrator(ABC):
    NAME = "base"

    @abstractmethod
    def build(self, job: JobRecord, services: Any) -> list[Any]:
        raise NotImplementedError
