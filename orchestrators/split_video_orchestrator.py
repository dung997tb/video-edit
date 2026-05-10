from __future__ import annotations

from orchestrators.base import PipelineOrchestrator


class SplitVideoOrchestrator(PipelineOrchestrator):
    NAME = "split_video"

    def build(self, job, services):
        from modules.video.split_video import SplitVideoModule

        return [SplitVideoModule(params=job.payload or {})]
