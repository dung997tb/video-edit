from __future__ import annotations

from core.models import StepResult
from core.process import run_subprocess
from modules.base import BaseModule
from modules.registry import register


@register
class FaceTrackerModule(BaseModule):
    NAME = "face_track_portrait"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"source_sha256": context.source_sha256}

    def execute(self, context, services) -> StepResult:
        width = int(self.params.get("output_width", 1080))
        height = int(self.params.get("output_height", 1920))
        output_path = context.file_manager.step_file("final")
        # MVP fallback: center reframe. A later plugin can replace this with
        # MediaPipe/OpenCV-generated crop expressions without changing callers.
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
        run_subprocess(
            [
                services.settings.ffmpeg_path,
                "-y",
                "-i",
                context.input_video,
                "-vf",
                vf,
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
            context_patch={"output_video": str(output_path), "metadata": {"face_tracking_mode": "center_fallback"}},
            artifacts={"output_video": str(output_path)},
        )
