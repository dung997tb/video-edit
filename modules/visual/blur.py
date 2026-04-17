from __future__ import annotations

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


@register
class VisualBlurModule(BaseModule):
    NAME = "visual_blur"

    def cache_inputs(self, context) -> dict:
        return {
            "luma_radius": self.params.get("luma_radius", 2),
            "luma_power": self.params.get("luma_power", 1),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services) -> StepResult:
        input_video = resolve_working_video(context)
        output_path = operation_output_path(context, self.params, self.NAME)
        luma_radius = float(self.params.get("luma_radius", 2))
        luma_power = float(self.params.get("luma_power", 1))
        vf = f"boxblur={luma_radius}:{luma_power}"
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
