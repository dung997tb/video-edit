from __future__ import annotations

from orchestrators.base import PipelineOrchestrator


class SilenceCutOrchestrator(PipelineOrchestrator):
    NAME = "silence_cut"

    def build(self, job, services):
        from modules.ai.silence_remover import SilenceRemoverModule

        payload = job.payload or {}
        return [SilenceRemoverModule(params=payload)]
