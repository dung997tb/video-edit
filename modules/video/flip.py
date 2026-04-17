from __future__ import annotations

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


def _resolve_flip_filter(mode: str) -> str:
    lowered = mode.lower().strip()
    if lowered in {"horizontal", "h", "x"}:
        return "hflip"
    if lowered in {"vertical", "v", "y"}:
        return "vflip"
    if lowered in {"both", "hv", "vh"}:
        return "hflip,vflip"
    raise ValueError("flip mode must be one of: horizontal, vertical, both")


@register
class FlipVideoModule(BaseModule):
    NAME = "flip"

    def cache_inputs(self, context) -> dict:
        return {"mode": self.params.get("mode", "horizontal")}

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services) -> StepResult:
        input_video = resolve_working_video(context)
        output_path = operation_output_path(context, self.params, self.NAME)
        vf = _resolve_flip_filter(str(self.params.get("mode", "horizontal")))
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
