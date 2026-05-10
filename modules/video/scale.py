from __future__ import annotations

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


def _build_scale_filter(width: int | None, height: int | None, keep_aspect: bool) -> str:
    if width is None and height is None:
        raise ValueError("scale operation requires width or height")
    if width is None:
        return f"scale=-2:{int(height)}:force_divisible_by=2"
    if height is None:
        return f"scale={int(width)}:-2:force_divisible_by=2"
    if keep_aspect:
        return f"scale={int(width)}:{int(height)}:force_original_aspect_ratio=decrease:force_divisible_by=2"
    return f"scale={int(width)}:{int(height)}"


@register
class ScaleVideoModule(BaseModule):
    NAME = "scale"

    def cache_inputs(self, context) -> dict:
        return {
            "width": self.params.get("width", self.params.get("w")),
            "height": self.params.get("height", self.params.get("h")),
            "keep_aspect": self.params.get("keep_aspect", True),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services) -> StepResult:
        input_video = resolve_working_video(context)
        output_path = operation_output_path(context, self.params, self.NAME)
        width = self.params.get("width", self.params.get("w"))
        height = self.params.get("height", self.params.get("h"))
        keep_aspect = bool(self.params.get("keep_aspect", True))
        vf = _build_scale_filter(
            width=int(width) if width is not None else None,
            height=int(height) if height is not None else None,
            keep_aspect=keep_aspect,
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
