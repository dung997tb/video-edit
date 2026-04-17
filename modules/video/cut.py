from __future__ import annotations

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


@register
class CutVideoModule(BaseModule):
    NAME = "cut"

    def cache_inputs(self, context) -> dict:
        return {
            "start": self.params.get("start"),
            "end": self.params.get("end"),
            "duration": self.params.get("duration"),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services) -> StepResult:
        input_video = resolve_working_video(context)
        output_path = operation_output_path(context, self.params, self.NAME)
        start = self.params.get("start")
        end = self.params.get("end")
        duration = self.params.get("duration")

        command = [services.settings.ffmpeg_path, "-y", "-i", input_video]
        if start is not None:
            command.extend(["-ss", f"{float(start):.3f}"])
        if end is not None:
            command.extend(["-to", f"{float(end):.3f}"])
        elif duration is not None:
            command.extend(["-t", f"{float(duration):.3f}"])
        command.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                str(self.params.get("crf", 23)),
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        run_ffmpeg(context, services, command)
        return working_video_result(output_path)
