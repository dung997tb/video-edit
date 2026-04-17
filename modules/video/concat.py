from __future__ import annotations

from pathlib import Path

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


def _concat_entry(path: str) -> str:
    escaped = path.replace("\\", "\\\\").replace("'", "'\\''")
    return f"file '{escaped}'"


@register
class ConcatVideoModule(BaseModule):
    NAME = "concat"

    def cache_inputs(self, context) -> dict:
        return {
            "inputs": self.params.get("inputs", []),
            "include_current": self.params.get("include_current", True),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services) -> StepResult:
        input_video = resolve_working_video(context)
        output_path = operation_output_path(context, self.params, self.NAME)
        include_current = bool(self.params.get("include_current", True))
        raw_inputs = self.params.get("inputs", [])
        if not isinstance(raw_inputs, list):
            raise ValueError("concat operation expects inputs as a list")
        sources = [str(Path(item)) for item in raw_inputs]
        if include_current:
            sources.insert(0, input_video)
        if len(sources) < 2:
            raise ValueError("concat operation requires at least two inputs")

        list_path = context.file_manager.temp(f"{int(self.params.get('op_index', 1)):02d}_concat_list.txt")
        list_path.write_text("\n".join(_concat_entry(path) for path in sources), encoding="utf-8")
        command = [
            services.settings.ffmpeg_path,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
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
        run_ffmpeg(context, services, command)
        return working_video_result(output_path)
