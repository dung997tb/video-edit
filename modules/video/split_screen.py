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
class SplitScreenModule(BaseModule):
    NAME = "split_screen"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context), "b_roll_video": self.params.get("b_roll_video")}

    def execute(self, context, services):
        b_roll_video = self.params.get("b_roll_video")
        if not b_roll_video:
            raise ValueError("split_screen requires b_roll_video")
        output_width = int(self.params.get("output_width", 1080))
        output_height = int(self.params.get("output_height", 1920))
        split_ratio = min(0.9, max(0.1, float(self.params.get("split_ratio", 0.5))))
        top_h = int(output_height * split_ratio)
        bottom_h = output_height - top_h
        fps = int(self.params.get("fps", 30))
        audio_source = str(self.params.get("audio_source", "main")).lower()
        duration_mode = str(self.params.get("duration_mode", "hold_last"))
        output_path = operation_output_path(context, self.params, self.NAME)
        main_norm = normalize_for_compose(
            resolve_working_video(context),
            output_width,
            top_h,
            fps=fps,
            input_start=_first_present(self.params, "main_start", "a_start", "first_start", "start"),
            input_end=_first_present(self.params, "main_end", "a_end", "first_end", "end"),
            input_duration=_first_present(self.params, "main_duration", "a_duration", "first_duration", "duration"),
            context=context,
            services=services,
            label=f"{self.params.get('op_index', 1):02d}_split_main",
        )
        b_norm = normalize_for_compose(
            str(Path(b_roll_video)),
            output_width,
            bottom_h,
            fps=fps,
            input_start=_first_present(self.params, "b_start", "b_roll_start", "second_start", "start"),
            input_end=_first_present(self.params, "b_end", "b_roll_end", "second_end", "end"),
            input_duration=_first_present(self.params, "b_duration", "b_roll_duration", "second_duration", "duration"),
            context=context,
            services=services,
            label=f"{self.params.get('op_index', 1):02d}_split_b",
        )
        main_norm, b_norm = align_compose_clips(
            [main_norm, b_norm],
            duration_mode=duration_mode,
            context=context,
            services=services,
            label=f"{self.params.get('op_index', 1):02d}_split_align",
        )
        command = [services.settings.ffmpeg_path, "-y"]
        if audio_source == "mix":
            main_norm = ensure_audio_stream(
                main_norm,
                probe_duration(main_norm, context, services),
                context=context,
                services=services,
                label=f"{self.params.get('op_index', 1):02d}_split_main",
            )
            b_norm = ensure_audio_stream(
                b_norm,
                probe_duration(b_norm, context, services),
                context=context,
                services=services,
                label=f"{self.params.get('op_index', 1):02d}_split_b",
            )
        command.extend(["-i", main_norm, "-i", b_norm])
        filter_graph = "[0:v][1:v]vstack=inputs=2[v]"
        if audio_source == "mix":
            filter_graph += ";[0:a][1:a]amix=inputs=2:duration=longest[a]"
        command.extend(["-filter_complex", filter_graph, "-map", "[v]"])
        if audio_source == "mix":
            command.extend(["-map", "[a]"])
        elif audio_source == "b_roll":
            command.extend(["-map", "1:a?"])
        else:
            command.extend(["-map", "0:a?"])
        command.extend(
            [
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
        )
        run_ffmpeg(context, services, command)
        return working_video_result(output_path)


def _first_present(params: dict, *keys: str):
    for key in keys:
        if key in params and params[key] is not None:
            return params[key]
    return None
