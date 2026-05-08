from __future__ import annotations

from orchestrators.base import PipelineOrchestrator


class MultilangDubbingOrchestrator(PipelineOrchestrator):
    NAME = "multilang-dubbing"

    def build(self, job, services):
        from modules.ai.multilang_fanout import MultilangFanOutModule

        return [MultilangFanOutModule()]
