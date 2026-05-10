from __future__ import annotations

from orchestrators.base import PipelineOrchestrator


class FaceTrackOrchestrator(PipelineOrchestrator):
    NAME = "face_track_portrait"

    def build(self, job, services):
        from modules.ai.face_tracker import FaceTrackerModule

        return [FaceTrackerModule(params=job.payload or {})]
