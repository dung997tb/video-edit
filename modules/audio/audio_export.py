from __future__ import annotations

import shutil
from pathlib import Path

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
        source = resolve_working_audio(context)
        if not source:
            raise ValueError("audio_export requires a source audio in context")
        extension = Path(source).suffix or ".wav"
        output_name = str(self.params.get("output_name", f"audio{extension}"))
        output = context.file_manager.output(output_name)
        shutil.copyfile(source, output)
        return StepResult(
            context_patch={"output_video": str(output), "metadata": {**context.metadata, "output_kind": "audio"}},
            artifacts={"output_audio": str(output)},
        )
