from __future__ import annotations

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register


@register
class SubtitleExportModule(BaseModule):
    NAME = "subtitle_export"

    def upstream_artifact_hashes(self, context) -> dict:
        return {
            "subtitle_path": context.subtitle_path or "",
            "burned_video": context.burned_video or "",
        }

    def execute(self, context, services) -> StepResult:
        output = context.burned_video or context.subtitle_path
        if not output:
            raise ValueError("subtitle_export requires subtitle_path or burned_video")
        return StepResult(
            context_patch={
                "output_video": output,
                "metadata": {**context.metadata, "output_kind": "video" if context.burned_video else "subtitle"},
            },
            artifacts={"output": output},
        )
