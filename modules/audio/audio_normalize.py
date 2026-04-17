from __future__ import annotations

from core.models import StepResult
from modules.audio.common import operation_output_path, resolve_working_audio, run_ffmpeg, working_audio_result
from modules.base import BaseModule
from modules.registry import register


@register
class AudioNormalizeModule(BaseModule):
    NAME = "audio_normalize"

    def cache_inputs(self, context) -> dict:
        return {
            "i": self.params.get("i", -16),
            "tp": self.params.get("tp", -1.5),
            "lra": self.params.get("lra", 11),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_audio": resolve_working_audio(context)}

    def execute(self, context, services) -> StepResult:
        input_audio = resolve_working_audio(context)
        if not input_audio:
            raise ValueError("audio_normalize requires a source audio in context")
        output_path = operation_output_path(context, self.params, self.NAME)
        i = float(self.params.get("i", -16))
        tp = float(self.params.get("tp", -1.5))
        lra = float(self.params.get("lra", 11))
        command = [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            input_audio,
            "-af",
            f"loudnorm=I={i}:TP={tp}:LRA={lra}",
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
