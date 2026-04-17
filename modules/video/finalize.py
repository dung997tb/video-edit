from __future__ import annotations

from core.models import StepResult
from core.process import SubprocessExecutionError
from modules.base import BaseModule
from modules.video.common import resolve_working_video, run_ffmpeg


class FinalizeVideoModule(BaseModule):
    NAME = "export_low_level"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services) -> StepResult:
        input_video = resolve_working_video(context)
        output_path = context.file_manager.step_file("final")
        copy_cmd = [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            input_video,
            "-c",
            "copy",
            str(output_path),
        ]
        try:
            run_ffmpeg(context, services, copy_cmd)
        except SubprocessExecutionError:
            fallback_cmd = [
                services.settings.ffmpeg_path,
                "-y",
                "-i",
                input_video,
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
            run_ffmpeg(context, services, fallback_cmd)
        return StepResult(
            context_patch={
                "output_video": str(output_path),
                "state": {"working_video": str(output_path)},
            },
            artifacts={"output_video": str(output_path)},
        )
