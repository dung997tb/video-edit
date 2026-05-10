from __future__ import annotations

from pathlib import Path

from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


@register
class ChromakeyModule(BaseModule):
    NAME = "chromakey"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context), "background_video": self.params.get("background_video")}

    def execute(self, context, services):
        background_video = self.params.get("background_video")
        if not background_video:
            raise ValueError("chromakey requires background_video")
        color = str(self.params.get("color", "#00FF00")).strip()
        if color.startswith("#"):
            color = "0x" + color[1:]
        similarity = float(self.params.get("similarity", 0.3))
        blend = float(self.params.get("blend", 0.1))
        output_path = operation_output_path(context, self.params, self.NAME)
        filter_graph = (
            f"[1:v]format=yuva420p,colorkey=color={color}:similarity={similarity}:blend={blend}[fg];"
            "[0:v][fg]overlay=format=auto[out]"
        )
        run_ffmpeg(
            context,
            services,
            [
                services.settings.ffmpeg_path,
                "-y",
                "-i",
                str(Path(background_video)),
                "-i",
                resolve_working_video(context),
                "-filter_complex",
                filter_graph,
                "-map",
                "[out]",
                "-map",
                "1:a?",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                str(self.params.get("crf", 23)),
                "-c:a",
                "aac",
                "-shortest",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
        )
        return working_video_result(output_path)
