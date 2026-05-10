from __future__ import annotations

from core.models import StepResult
from core.process import run_subprocess
from core.semantic import HookDetector, PacingAnalyzer, SilenceDetector
from core.timeline import TimelineBuilder
from modules.base import BaseModule
from modules.registry import register


@register
class SemanticEditModule(BaseModule):
    NAME = "semantic_edit"

    def cache_inputs(self, context) -> dict:
        return {
            "command": context.state.get("command", self.params.get("command", "make_tiktok_short")),
            "target_duration": context.state.get("target_duration", self.params.get("target_duration", 60)),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {"source_sha256": context.source_sha256, "segments": context.segments}

    def execute(self, context, services) -> StepResult:
        command = str(context.state.get("command", self.params.get("command", "make_tiktok_short")))
        target_duration = float(context.state.get("target_duration", self.params.get("target_duration", 60)))
        start = float(context.state.get("start", 0.0))
        if command == "make_tiktok_short" and context.segments:
            hook = HookDetector(window_seconds=min(target_duration, 30.0)).analyze(context.segments)
            start = max(0.0, float(hook.get("start", 0.0)))
        end = start + max(target_duration, 0.5)
        timeline = TimelineBuilder(duration=end - start).add_video(context.input_video, start=start, end=end).build()
        metadata = dict(context.metadata)
        metadata["semantic"] = {
            "command": command,
            "timeline": timeline.to_dict(),
            "silence_gaps": SilenceDetector().analyze(context.segments),
            "pacing": PacingAnalyzer().analyze(context.segments),
        }
        output_path = context.file_manager.step_file("final")
        run_subprocess(
            [
                services.settings.ffmpeg_path,
                "-y",
                "-ss",
                f"{start:.3f}",
                "-i",
                context.input_video,
                "-t",
                f"{end - start:.3f}",
                "-c",
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
            context_patch={"output_video": str(output_path), "metadata": metadata},
            artifacts={"output_video": str(output_path)},
        )
