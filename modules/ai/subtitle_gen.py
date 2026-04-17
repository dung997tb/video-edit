from __future__ import annotations

from core.cache import stable_value_signature
from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register


def _format_timestamp(seconds: float) -> str:
    total_ms = int(seconds * 1000)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


@register
class SubtitleModule(BaseModule):
    NAME = "subtitle"

    def upstream_artifact_hashes(self, context) -> dict:
        source_segments = context.translated_segments or context.segments
        return {
            "segments": stable_value_signature({"segments": source_segments}),
        }

    def execute(self, context, services) -> StepResult:
        source_segments = context.translated_segments or context.segments
        if not source_segments:
            raise ValueError("segments are required before subtitle generation")
        output_path = context.file_manager.step_file("subtitle")
        lines: list[str] = []
        for index, segment in enumerate(source_segments, start=1):
            lines.append(str(index))
            lines.append(f"{_format_timestamp(segment['start'])} --> {_format_timestamp(segment['end'])}")
            lines.append(segment["text"].strip())
            lines.append("")
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return StepResult(
            context_patch={"subtitle_path": str(output_path)},
            artifacts={"subtitle": str(output_path)},
        )
