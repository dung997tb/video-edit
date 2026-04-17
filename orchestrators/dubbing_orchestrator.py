from __future__ import annotations

from orchestrators.base import PipelineOrchestrator


class DubbingOrchestrator(PipelineOrchestrator):
    NAME = "dubbing"

    def build(self, job, services):
        from modules.ai.dubbing import build_dubbing_pipeline

        return build_dubbing_pipeline(job, services)
