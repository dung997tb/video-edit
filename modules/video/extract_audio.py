from __future__ import annotations

from core.models import StepResult
from core.process import run_subprocess
from modules.base import BaseModule
from modules.registry import register


@register
class ExtractAudioModule(BaseModule):
    NAME = "extract_audio"

    def cache_inputs(self, context) -> dict:
        return {
            "sample_rate": self.params.get("sample_rate", 16000),
            "channels": self.params.get("channels", 1),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {"source_sha256": context.source_sha256}

    def execute(self, context, services) -> StepResult:
        output_path = context.file_manager.step_file("extract_audio")
        command = [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            context.input_video,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(self.params.get("sample_rate", 16000)),
            "-ac",
            str(self.params.get("channels", 1)),
            str(output_path),
        ]
        run_subprocess(
            command,
            job_id=context.job_id,
            job_manager=services.job_manager,
            process_registry=services.process_registry,
            cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
            grace_seconds=services.settings.cancel_grace_seconds,
        )
        return StepResult(
            context_patch={"audio_path": str(output_path)},
            artifacts={"audio_path": str(output_path)},
        )
