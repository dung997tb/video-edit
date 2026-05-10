from __future__ import annotations

import shutil

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
        if context.burned_video:
            final_output = context.file_manager.step_file("final")
            if str(final_output) != str(context.burned_video):
                final_output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(context.burned_video, final_output)
            output = str(final_output)
        return StepResult(
            context_patch={
                "output_video": output,
                "metadata": {**context.metadata, "output_kind": "video" if context.burned_video else "subtitle"},
            },
            artifacts={"output": output},
        )
