from __future__ import annotations

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


@register
class ColorGradeVideoModule(BaseModule):
    NAME = "color_grade"

    def cache_inputs(self, context) -> dict:
        return {
            "brightness": self.params.get("brightness", 0.0),
            "contrast": self.params.get("contrast", 1.0),
            "saturation": self.params.get("saturation", 1.0),
            "gamma": self.params.get("gamma", 1.0),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services) -> StepResult:
        input_video = resolve_working_video(context)
        output_path = operation_output_path(context, self.params, self.NAME)
        brightness = float(self.params.get("brightness", 0.0))
        contrast = float(self.params.get("contrast", 1.0))
        saturation = float(self.params.get("saturation", 1.0))
        gamma = float(self.params.get("gamma", 1.0))
        vf = (
            f"eq=brightness={brightness:.4f}:"
            f"contrast={contrast:.4f}:"
            f"saturation={saturation:.4f}:"
            f"gamma={gamma:.4f}"
        )
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
