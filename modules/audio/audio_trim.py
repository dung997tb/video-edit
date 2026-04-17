from __future__ import annotations

from core.models import StepResult
from modules.audio.common import operation_output_path, resolve_working_audio, run_ffmpeg, working_audio_result
from modules.base import BaseModule
from modules.registry import register


@register
class AudioTrimModule(BaseModule):
    NAME = "audio_trim"

    def cache_inputs(self, context) -> dict:
        return {
            "start": self.params.get("start"),
            "end": self.params.get("end"),
            "duration": self.params.get("duration"),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_audio": resolve_working_audio(context)}

    def execute(self, context, services) -> StepResult:
        input_audio = resolve_working_audio(context)
        if not input_audio:
            raise ValueError("audio_trim requires a source audio in context")
        output_path = operation_output_path(context, self.params, self.NAME)
        start = self.params.get("start")
        end = self.params.get("end")
        duration = self.params.get("duration")

        command = [services.settings.ffmpeg_path, "-y", "-i", input_audio]
        if start is not None:
            command.extend(["-ss", f"{float(start):.3f}"])
        if end is not None:
            command.extend(["-to", f"{float(end):.3f}"])
        elif duration is not None:
            command.extend(["-t", f"{float(duration):.3f}"])
        command.extend(
            [
                "-ar",
                str(self.params.get("sample_rate", 24000)),
                "-ac",
                str(self.params.get("channels", 1)),
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ]
        )
        run_ffmpeg(context, services, command)
        return working_audio_result(output_path)
