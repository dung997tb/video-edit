from __future__ import annotations

from core.models import StepResult
from core.process import run_subprocess
from modules.base import BaseModule
from modules.registry import register


@register
class RemuxAudioModule(BaseModule):
    NAME = "final"

    def upstream_artifact_hashes(self, context) -> dict:
        return {
            "video_input": context.burned_video or context.source_sha256,
            "mixed_audio": context.mixed_audio or context.synced_audio or "",
        }

    def execute(self, context, services) -> StepResult:
        audio_input = context.mixed_audio or context.synced_audio
        if not audio_input:
            raise ValueError("missing audio input for final remux")
        video_input = context.burned_video or context.input_video
        video_duration = self._probe_duration(video_input, context, services)
        output_path = context.file_manager.step_file("final")
        command = [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            video_input,
            "-i",
            audio_input,
            "-filter_complex",
            f"[1:a]apad,atrim=duration={video_duration:.3f}[aout]",
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        run_subprocess(
            command,
            job_id=context.job_id,
            job_manager=services.job_manager,
            process_registry=services.process_registry,
            cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
            grace_seconds=services.settings.cancel_grace_seconds,
        )
        return StepResult(
            context_patch={"output_video": str(output_path)},
            artifacts={"output_video": str(output_path)},
        )

    def _probe_duration(self, video_path: str, context, services) -> float:
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
        try:
            duration = float(result.stdout.strip())
        except ValueError as exc:
            raise RuntimeError(f"unable to parse ffprobe duration for {video_path}") from exc
        if duration <= 0:
            raise RuntimeError(f"invalid video duration from ffprobe: {duration}")
        return duration
