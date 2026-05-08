from __future__ import annotations

from modules.audio.common import resolve_working_audio
from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register


@register
class AudioExportModule(BaseModule):
    NAME = "audio_export"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_audio": resolve_working_audio(context)}

    def execute(self, context, services) -> StepResult:
        output = resolve_working_audio(context)
        if not output:
            raise ValueError("audio_export requires a source audio in context")
        return StepResult(
            context_patch={"output_video": output, "metadata": {**context.metadata, "output_kind": "audio"}},
            artifacts={"output_audio": output},
        )
