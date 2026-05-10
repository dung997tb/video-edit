from __future__ import annotations

from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


@register
class BlurBgPortraitModule(BaseModule):
    NAME = "blur_bg_portrait"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services):
        width = int(self.params.get("output_width", 1080))
        height = int(self.params.get("output_height", 1920))
        blur = float(self.params.get("blur_sigma", 25))
        output_path = operation_output_path(context, self.params, self.NAME)
        filter_graph = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},boxblur={blur}:5[bg];"
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2:shortest=1[out]"
        )
        run_ffmpeg(
            context,
            services,
            [
                services.settings.ffmpeg_path,
                "-y",
                "-i",
                resolve_working_video(context),
                "-filter_complex",
                filter_graph,
                "-map",
                "[out]",
                "-map",
                "0:a?",
                "-c:a",
                "copy",
                str(output_path),
            ],
        )
        return working_video_result(output_path)
