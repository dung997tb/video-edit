from __future__ import annotations

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


@register
class CropVideoModule(BaseModule):
    NAME = "crop"

    def cache_inputs(self, context) -> dict:
        return {
            "width": self.params.get("width"),
            "height": self.params.get("height"),
            "x": self.params.get("x", 0),
            "y": self.params.get("y", 0),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services) -> StepResult:
        input_video = resolve_working_video(context)
        output_path = operation_output_path(context, self.params, self.NAME)
        width = self.params.get("width")
        height = self.params.get("height")
        if width is None or height is None:
            raise ValueError("crop operation requires width and height")
        x = int(self.params.get("x", 0))
        y = int(self.params.get("y", 0))
        vf = f"crop={int(width)}:{int(height)}:{x}:{y}"
        command = [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            input_video,
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(self.params.get("crf", 23)),
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        run_ffmpeg(context, services, command)
        return working_video_result(output_path)
