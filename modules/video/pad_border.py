from __future__ import annotations

from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


@register
class PadBorderModule(BaseModule):
    NAME = "pad_border"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services):
        size = max(0, int(self.params.get("size", 20)))
        color = str(self.params.get("color", "black"))
        output_path = operation_output_path(context, self.params, self.NAME)
        run_ffmpeg(
            context,
            services,
            [
                services.settings.ffmpeg_path,
                "-y",
                "-i",
                resolve_working_video(context),
                "-vf",
                f"pad=iw+{size * 2}:ih+{size * 2}:{size}:{size}:color={color}",
                "-c:a",
                "copy",
                str(output_path),
            ],
        )
        return working_video_result(output_path)
