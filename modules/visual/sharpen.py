from __future__ import annotations

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


@register
class VisualSharpenModule(BaseModule):
    NAME = "visual_sharpen"

    def cache_inputs(self, context) -> dict:
        return {
            "luma_msize_x": self.params.get("luma_msize_x", 5),
            "luma_msize_y": self.params.get("luma_msize_y", 5),
            "luma_amount": self.params.get("luma_amount", 1.0),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services) -> StepResult:
        input_video = resolve_working_video(context)
        output_path = operation_output_path(context, self.params, self.NAME)
        size_x = int(self.params.get("luma_msize_x", 5))
        size_y = int(self.params.get("luma_msize_y", 5))
        amount = float(self.params.get("luma_amount", 1.0))
        vf = f"unsharp={size_x}:{size_y}:{amount:.3f}:5:5:0.0"
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
