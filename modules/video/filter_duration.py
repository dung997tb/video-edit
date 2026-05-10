from __future__ import annotations

from core.models import StepResult
from core.process import run_subprocess
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import resolve_working_video


@register
class FilterDurationModule(BaseModule):
    NAME = "filter_duration"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services) -> StepResult:
        duration = _probe_duration(resolve_working_video(context), context, services)
        min_seconds = self.params.get("min_seconds")
        max_seconds = self.params.get("max_seconds")
        if min_seconds is not None and duration < float(min_seconds):
            raise ValueError(f"video duration {duration:.3f}s is below min_seconds={float(min_seconds):.3f}")
        if max_seconds is not None and duration > float(max_seconds):
            raise ValueError(f"video duration {duration:.3f}s exceeds max_seconds={float(max_seconds):.3f}")
        return StepResult(context_patch={"metadata": {"duration_seconds": duration}})


def _probe_duration(video_path: str, context, services) -> float:
    result = run_subprocess(
        [
            services.settings.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            video_path,
        ],
        job_id=context.job_id,
        job_manager=services.job_manager,
        process_registry=services.process_registry,
        cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
        grace_seconds=services.settings.cancel_grace_seconds,
        timeout=30,
    )
    return float(result.stdout.strip())
