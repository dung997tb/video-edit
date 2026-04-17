from __future__ import annotations

from core.models import StepResult
from core.process import SubprocessExecutionError
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import atempo_chain, operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


@register
class SpeedVideoModule(BaseModule):
    NAME = "speed"

    def cache_inputs(self, context) -> dict:
        return {"factor": self.params.get("factor", 1.0)}

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services) -> StepResult:
        input_video = resolve_working_video(context)
        output_path = operation_output_path(context, self.params, self.NAME)
        factor = float(self.params.get("factor", 1.0))
        if factor <= 0:
            raise ValueError("speed factor must be > 0")

        video_pts = 1.0 / factor
        audio_filters = ",".join(atempo_chain(factor))
        primary = [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            input_video,
            "-filter_complex",
            f"[0:v]setpts={video_pts:.6f}*PTS[v];[0:a]{audio_filters}[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(self.params.get("crf", 23)),
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        try:
            run_ffmpeg(context, services, primary)
        except SubprocessExecutionError:
            # Fallback for silent videos without an audio stream.
            fallback = [
                services.settings.ffmpeg_path,
                "-y",
                "-i",
                input_video,
                "-vf",
                f"setpts={video_pts:.6f}*PTS",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                str(self.params.get("crf", 23)),
                "-movflags",
                "+faststart",
                str(output_path),
            ]
            run_ffmpeg(context, services, fallback)
        return working_video_result(output_path)
