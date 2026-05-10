from __future__ import annotations

from pathlib import Path

from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


def _concat_entry(path: str) -> str:
    escaped = str(Path(path).resolve()).replace("\\", "\\\\").replace("'", "'\\''")
    return f"file '{escaped}'"


@register
class LoopVideoModule(BaseModule):
    NAME = "loop"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services):
        times = max(1, int(self.params.get("times", 2)))
        input_video = resolve_working_video(context)
        output_path = operation_output_path(context, self.params, self.NAME)
        list_path = context.file_manager.temp(f"{int(self.params.get('op_index', 1)):02d}_loop_list.txt")
        list_path.write_text("\n".join(_concat_entry(input_video) for _ in range(times)), encoding="utf-8")
        run_ffmpeg(
            context,
            services,
            [
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
            ],
        )
        return working_video_result(output_path)
