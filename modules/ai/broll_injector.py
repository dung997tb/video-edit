from __future__ import annotations

from core.models import StepResult
from core.process import run_subprocess
from modules.base import BaseModule
from modules.registry import register


@register
class BrollInjectorModule(BaseModule):
    NAME = "auto_broll"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"segments": context.segments, "source_sha256": context.source_sha256}

    def execute(self, context, services) -> StepResult:
        keyword_map = context.state.get("keyword_map") or self.params.get("keyword_map") or {}
        match = _find_match(context.segments, keyword_map)
        output_path = context.file_manager.step_file("final")
        if match is None:
            run_subprocess(
                [services.settings.ffmpeg_path, "-y", "-i", context.input_video, "-c", "copy", str(output_path)],
                job_id=context.job_id,
                job_manager=services.job_manager,
                process_registry=services.process_registry,
                cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
                grace_seconds=services.settings.cancel_grace_seconds,
            )
            return StepResult(
                context_patch={"output_video": str(output_path), "metadata": {"broll_matches": 0}},
                artifacts={"output_video": str(output_path)},
            )

        broll_path, start, end = match
        filter_graph = (
            "[1:v]scale=iw*0.38:-2[broll];"
            f"[0:v][broll]overlay=W-w-40:40:enable='between(t,{start:.3f},{end:.3f})'[outv]"
        )
        run_subprocess(
            [
                services.settings.ffmpeg_path,
                "-y",
                "-i",
                context.input_video,
                "-i",
                broll_path,
                "-filter_complex",
                filter_graph,
                "-map",
                "[outv]",
                "-map",
                "0:a?",
                str(output_path),
            ],
            job_id=context.job_id,
            job_manager=services.job_manager,
            process_registry=services.process_registry,
            cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
            grace_seconds=services.settings.cancel_grace_seconds,
        )
        return StepResult(
            context_patch={"output_video": str(output_path), "metadata": {"broll_matches": 1}},
            artifacts={"output_video": str(output_path)},
        )


def _find_match(segments: list[dict], keyword_map: dict) -> tuple[str, float, float] | None:
    lowered_map = {str(keyword).lower(): str(path) for keyword, path in keyword_map.items()}
    for segment in segments:
        text = str(segment.get("text", "")).lower()
        for keyword, path in lowered_map.items():
            if keyword in text:
                return path, float(segment.get("start", 0.0)), float(segment.get("end", 0.0))
    return None
