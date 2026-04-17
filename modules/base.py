from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from core.models import StepResult

if TYPE_CHECKING:
    from core.context import PipelineContext


class BaseModule(ABC):
    NAME = "base"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = params or {}

    def cache_inputs(self, context: "PipelineContext") -> dict[str, Any]:
        return dict(self.params)

    def upstream_artifact_hashes(self, context: "PipelineContext") -> dict[str, Any]:
        return {}

    @abstractmethod
    def execute(self, context: "PipelineContext", services: Any) -> StepResult:
        raise NotImplementedError
