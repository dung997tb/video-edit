from __future__ import annotations

from orchestrators.base import PipelineOrchestrator


class LowLevelOrchestrator(PipelineOrchestrator):
    NAME = "low_level"

    def build(self, job, services):
        from modules.video.low_level import build_low_level_pipeline

        return build_low_level_pipeline(job, services)
