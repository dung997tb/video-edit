from __future__ import annotations

from core.models import StepResult
from modules.audio.common import operation_output_path, resolve_working_audio, run_ffmpeg, working_audio_result
from modules.base import BaseModule
from modules.registry import register


@register
class AudioVolumeModule(BaseModule):
    NAME = "audio_volume"

    def cache_inputs(self, context) -> dict:
        return {"volume": self.params.get("volume", "1.0")}

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_audio": resolve_working_audio(context)}

    def execute(self, context, services) -> StepResult:
        input_audio = resolve_working_audio(context)
        if not input_audio:
            raise ValueError("audio_volume requires a source audio in context")
        output_path = operation_output_path(context, self.params, self.NAME)
        volume = str(self.params.get("volume", "1.0"))
        command = [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            input_audio,
            "-af",
            f"volume={volume}",
            "-ar",
            str(self.params.get("sample_rate", 24000)),
            "-ac",
            str(self.params.get("channels", 1)),
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
        run_ffmpeg(context, services, command)
        return working_audio_result(output_path)
