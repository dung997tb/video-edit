from __future__ import annotations

from pathlib import Path

from modules.base import BaseModule
from modules.registry import register
from modules.video.common import (
    align_compose_clips,
    ensure_audio_stream,
    normalize_for_compose,
    operation_output_path,
    probe_duration,
    resolve_working_video,
    run_ffmpeg,
    working_video_result,
)


@register
class HStackModule(BaseModule):
    NAME = "hstack"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context), "second_video": self.params.get("second_video")}

    def execute(self, context, services):
        second_video = self.params.get("second_video")
        if not second_video:
            raise ValueError("hstack requires second_video")
        first = resolve_working_video(context)
        second = str(Path(second_video))
        layout = str(self.params.get("layout", "horizontal")).lower()
        fps = int(self.params.get("fps", 30))
        duration_mode = str(self.params.get("duration_mode", "hold_last"))
        output_path = operation_output_path(context, self.params, self.NAME)
        if layout == "vertical":
            cell_w = int(self.params.get("cell_width", self.params.get("output_width", 1080)))
            cell_h = int(self.params.get("cell_height", int(self.params.get("output_height", 1920)) // 2))
            stack_filter = "vstack=inputs=2"
        else:
            cell_w = int(self.params.get("cell_width", int(self.params.get("output_width", 1280)) // 2))
            cell_h = int(self.params.get("cell_height", self.params.get("output_height", 720)))
            stack_filter = "hstack=inputs=2"

        first_norm = normalize_for_compose(
            first,
            cell_w,
            cell_h,
            fps=fps,
            input_start=_first_present(self.params, "a_start", "first_start", "main_start", "start"),
            input_end=_first_present(self.params, "a_end", "first_end", "main_end", "end"),
            input_duration=_first_present(self.params, "a_duration", "first_duration", "main_duration", "duration"),
            context=context,
            services=services,
            label=f"{self.params.get('op_index', 1):02d}_hstack_a",
        )
        second_norm = normalize_for_compose(
            second,
            cell_w,
            cell_h,
            fps=fps,
            input_start=_first_present(self.params, "b_start", "second_start", "start"),
            input_end=_first_present(self.params, "b_end", "second_end", "end"),
            input_duration=_first_present(self.params, "b_duration", "second_duration", "duration"),
            context=context,
            services=services,
            label=f"{self.params.get('op_index', 1):02d}_hstack_b",
        )
        first_norm, second_norm = align_compose_clips(
            [first_norm, second_norm],
            duration_mode=duration_mode,
            context=context,
            services=services,
            label=f"{self.params.get('op_index', 1):02d}_hstack_align",
        )
        first_audio = ensure_audio_stream(
            first_norm,
            probe_duration(first_norm, context, services),
            context=context,
            services=services,
            label=f"{self.params.get('op_index', 1):02d}_hstack_a",
        )
        second_audio = ensure_audio_stream(
            second_norm,
            probe_duration(second_norm, context, services),
            context=context,
            services=services,
            label=f"{self.params.get('op_index', 1):02d}_hstack_b",
        )
        run_ffmpeg(
            context,
            services,
            [
                services.settings.ffmpeg_path,
                "-y",
                "-i",
                first_audio,
                "-i",
                second_audio,
                "-filter_complex",
                f"[0:v][1:v]{stack_filter}[v];[0:a][1:a]amix=inputs=2:duration=longest[a]",
                "-map",
                "[v]",
                "-map",
                "[a]",
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


def _first_present(params: dict, *keys: str):
    for key in keys:
        if key in params and params[key] is not None:
            return params[key]
    return None
