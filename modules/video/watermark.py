from __future__ import annotations

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


@register
class WatermarkVideoModule(BaseModule):
    NAME = "watermark"

    def cache_inputs(self, context) -> dict:
        return {
            "watermark_path": self.params.get("watermark_path"),
            "x": self.params.get("x", 16),
            "y": self.params.get("y", 16),
            "opacity": self.params.get("opacity", 0.7),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services) -> StepResult:
        input_video = resolve_working_video(context)
        output_path = operation_output_path(context, self.params, self.NAME)
        watermark_path = self.params.get("watermark_path") or self.params.get("overlay_path")
        if not watermark_path:
            raise ValueError("watermark operation requires watermark_path")
        x = int(self.params.get("x", 16))
        y = int(self.params.get("y", 16))
        opacity = float(self.params.get("opacity", 0.7))
        if opacity < 0 or opacity > 1:
            raise ValueError("watermark opacity must be between 0 and 1")
        filter_graph = (
            f"[1:v]format=rgba,colorchannelmixer=aa={opacity:.3f}[wm];"
            f"[0:v][wm]overlay={x}:{y}[v]"
        )
        command = [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            input_video,
            "-i",
            str(watermark_path),
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
