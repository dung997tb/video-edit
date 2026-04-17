from __future__ import annotations

from core.models import StepResult
from modules.audio.common import operation_output_path, resolve_working_audio, run_ffmpeg, working_audio_result
from modules.base import BaseModule
from modules.registry import register


@register
class AudioFadeModule(BaseModule):
    NAME = "audio_fade"

    def cache_inputs(self, context) -> dict:
        return {
            "fade_in_duration": self.params.get("fade_in_duration", 0.0),
            "fade_out_start": self.params.get("fade_out_start", 0.0),
            "fade_out_duration": self.params.get("fade_out_duration", 0.0),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_audio": resolve_working_audio(context)}

    def execute(self, context, services) -> StepResult:
        input_audio = resolve_working_audio(context)
        if not input_audio:
            raise ValueError("audio_fade requires a source audio in context")
        output_path = operation_output_path(context, self.params, self.NAME)
        fade_in_duration = float(self.params.get("fade_in_duration", 0.0))
        fade_out_start = float(self.params.get("fade_out_start", 0.0))
        fade_out_duration = float(self.params.get("fade_out_duration", 0.0))

        filters: list[str] = []
        if fade_in_duration > 0:
            filters.append(f"afade=t=in:st=0:d={fade_in_duration:.3f}")
        if fade_out_duration > 0:
            filters.append(f"afade=t=out:st={fade_out_start:.3f}:d={fade_out_duration:.3f}")
        af = ",".join(filters) if filters else "anull"
        command = [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            input_audio,
            "-af",
            af,
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
