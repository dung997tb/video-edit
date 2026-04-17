from __future__ import annotations

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


@register
class OverlayVideoModule(BaseModule):
    NAME = "overlay"

    def cache_inputs(self, context) -> dict:
        return {
            "overlay_path": self.params.get("overlay_path"),
            "x": self.params.get("x", 0),
            "y": self.params.get("y", 0),
            "overlay_width": self.params.get("overlay_width"),
            "overlay_height": self.params.get("overlay_height"),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services) -> StepResult:
        input_video = resolve_working_video(context)
        output_path = operation_output_path(context, self.params, self.NAME)
        overlay_path = self.params.get("overlay_path")
        if not overlay_path:
            raise ValueError("overlay operation requires overlay_path")
        x = int(self.params.get("x", 0))
        y = int(self.params.get("y", 0))
        width = self.params.get("overlay_width")
        height = self.params.get("overlay_height")

        if width is None and height is None:
            filter_graph = f"[0:v][1:v]overlay={x}:{y}:shortest=1[v]"
        else:
            w_value = int(width) if width is not None else -1
            h_value = int(height) if height is not None else -1
            filter_graph = (
                f"[1:v]scale={w_value}:{h_value}[ov];"
                f"[0:v][ov]overlay={x}:{y}:shortest=1[v]"
            )

        command = [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            input_video,
            "-i",
            str(overlay_path),
            "-filter_complex",
            filter_graph,
            "-map",
            "[v]",
            "-map",
            "0:a?",
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
