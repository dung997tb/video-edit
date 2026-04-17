from __future__ import annotations

from core.models import StepResult
from core.process import run_subprocess
from modules.base import BaseModule
from modules.registry import register


def build_audio_filter_complex(track_count: int, background_weight: float = 0.15) -> str:
    if track_count <= 0:
        raise ValueError("track_count must be positive")
    if track_count == 1:
        return "[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[out]"
    if track_count != 2:
        raise ValueError("audio mixer currently supports one or two tracks")
    return (
        "[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[a0];"
        "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[a1];"
        f"[a0][a1]amix=inputs=2:duration=longest:weights='1 {background_weight}'[out]"
    )


@register
class AudioMixerModule(BaseModule):
    NAME = "mixed_audio"

    def cache_inputs(self, context) -> dict:
        return {
            "background_weight": self.params.get("background_weight", 0.15),
            "background_audio": context.state.get("background_audio") or context.state.get("background_music"),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {
            "synced_audio": context.synced_audio or "",
            "background_audio": context.state.get("background_audio") or context.state.get("background_music") or "",
        }

    def execute(self, context, services) -> StepResult:
        if not context.synced_audio:
            raise ValueError("synced_audio is required before mixing")
        background_audio = context.state.get("background_audio") or context.state.get("background_music")
        output_path = context.file_manager.step_file("mixed_audio")
        command = [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            context.synced_audio,
        ]
        track_count = 1
        if background_audio:
            command.extend(["-i", background_audio])
            track_count = 2
        command.extend(
            [
                "-filter_complex",
                build_audio_filter_complex(
                    track_count=track_count,
                    background_weight=float(self.params.get("background_weight", 0.15)),
                ),
                "-map",
                "[out]",
                str(output_path),
            ]
        )
        run_subprocess(
            command,
            job_id=context.job_id,
            job_manager=services.job_manager,
            process_registry=services.process_registry,
            cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
            grace_seconds=services.settings.cancel_grace_seconds,
        )
        return StepResult(
            context_patch={"mixed_audio": str(output_path)},
            artifacts={"mixed_audio": str(output_path)},
        )
