from __future__ import annotations

from orchestrators.base import PipelineOrchestrator


class ExtractFramesOrchestrator(PipelineOrchestrator):
    NAME = "extract_frames"

    def build(self, job, services):
        from modules.video.extract_frames import ExtractFramesModule

        return [ExtractFramesModule(params=job.payload or {})]
