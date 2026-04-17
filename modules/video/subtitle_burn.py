from __future__ import annotations

from pathlib import Path

from core.models import StepResult
from core.process import run_subprocess
from modules.base import BaseModule
from modules.registry import register


def _escape_subtitle_path(path: str | Path) -> str:
    resolved = Path(path).resolve().as_posix()
    resolved = resolved.replace(":", "\\:")
    return resolved.replace("'", "\\'")


@register
class SubtitleBurnModule(BaseModule):
    NAME = "burned_video"

    def upstream_artifact_hashes(self, context) -> dict:
        return {
            "source_sha256": context.source_sha256,
            "subtitle_path": context.subtitle_path or "",
        }

    def execute(self, context, services) -> StepResult:
        if not context.subtitle_path:
            raise ValueError("subtitle_path is required before subtitle burn")
        output_path = context.file_manager.step_file("burned_video")
        subtitle_filter = f"subtitles='{_escape_subtitle_path(context.subtitle_path)}'"
        run_subprocess(
            [
                services.settings.ffmpeg_path,
                "-y",
                "-i",
                context.input_video,
                "-vf",
                subtitle_filter,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "copy",
                str(output_path),
            ],
            job_id=context.job_id,
            job_manager=services.job_manager,
            process_registry=services.process_registry,
            cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
            grace_seconds=services.settings.cancel_grace_seconds,
        )
        return StepResult(
            context_patch={"burned_video": str(output_path)},
            artifacts={"burned_video": str(output_path)},
        )
