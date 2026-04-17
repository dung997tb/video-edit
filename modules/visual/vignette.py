from __future__ import annotations

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


@register
class VisualVignetteModule(BaseModule):
    NAME = "visual_vignette"

    def cache_inputs(self, context) -> dict:
        return {"angle": self.params.get("angle", "PI/5")}

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services) -> StepResult:
        input_video = resolve_working_video(context)
        output_path = operation_output_path(context, self.params, self.NAME)
        angle = str(self.params.get("angle", "PI/5"))
        command = [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            input_video,
            "-vf",
            f"vignette=angle={angle}",
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
