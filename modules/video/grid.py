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
class GridModule(BaseModule):
    NAME = "grid"

    def upstream_artifact_hashes(self, context) -> dict:
        return {
            "working_video": resolve_working_video(context),
            "videos": self.params.get("videos", []),
            "video_inputs": self.params.get("video_inputs", []),
        }

    def execute(self, context, services):
        sources = _resolve_grid_sources(self.params, context)
        cols = max(1, int(self.params.get("cols", 2)))
        rows = max(1, int(self.params.get("rows", 2)))
        required = cols * rows
        if len(sources) < required:
            raise ValueError(f"grid requires at least {required} videos for {cols}x{rows}")
        sources = sources[:required]
        output_width = int(self.params.get("output_width", 1080))
        output_height = int(self.params.get("output_height", 1920))
        cell_w = max(2, output_width // cols)
        cell_h = max(2, output_height // rows)
        fps = int(self.params.get("fps", 30))
        duration_mode = str(self.params.get("duration_mode", "hold_last"))
        normalized = []
        for index, source in enumerate(sources):
            normalized_path = normalize_for_compose(
                source["path"],
                cell_w,
                cell_h,
                fps=fps,
                input_start=source.get("start", self.params.get("start")),
                input_end=source.get("end", self.params.get("end")),
                input_duration=source.get("duration", self.params.get("duration")),
                context=context,
                services=services,
                label=f"{self.params.get('op_index', 1):02d}_grid_{index}",
            )
            normalized.append(normalized_path)
        normalized = align_compose_clips(
            normalized,
            duration_mode=duration_mode,
            context=context,
            services=services,
            label=f"{self.params.get('op_index', 1):02d}_grid_align",
        )
        with_audio = []
        for index, normalized_path in enumerate(normalized):
            with_audio.append(
                ensure_audio_stream(
                    normalized_path,
                    probe_duration(normalized_path, context, services),
                    context=context,
                    services=services,
                    label=f"{self.params.get('op_index', 1):02d}_grid_{index}",
                )
            )

        filter_parts: list[str] = []
        row_labels: list[str] = []
        for row in range(rows):
            inputs = "".join(f"[{row * cols + col}:v]" for col in range(cols))
            row_label = f"row{row}"
            filter_parts.append(f"{inputs}hstack=inputs={cols}[{row_label}]")
            row_labels.append(f"[{row_label}]")
        filter_parts.append("".join(row_labels) + f"vstack=inputs={rows}[v]")
        audio_inputs = "".join(f"[{index}:a]" for index in range(required))
        filter_parts.append(f"{audio_inputs}amix=inputs={required}:duration=longest[a]")
        output_path = operation_output_path(context, self.params, self.NAME)
        command = [services.settings.ffmpeg_path, "-y"]
        for path in with_audio:
            command.extend(["-i", path])
        command.extend(
            [
                "-filter_complex",
                ";".join(filter_parts),
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
            ]
        )
        run_ffmpeg(context, services, command)
        return working_video_result(output_path)


def _resolve_grid_sources(params: dict, context) -> list[dict]:
    video_inputs = params.get("video_inputs")
    if video_inputs is not None:
        if not isinstance(video_inputs, list):
            raise ValueError("grid expects video_inputs as a list")
        sources = []
        for item in video_inputs:
            if isinstance(item, str):
                sources.append({"path": str(Path(item))})
                continue
            if not isinstance(item, dict):
                raise ValueError("grid video_inputs items must be strings or objects")
            source_name = str(item.get("source", "")).lower()
            path = item.get("path") or item.get("video") or item.get("input")
            if source_name in {"current", "working", "main"}:
                path = resolve_working_video(context)
            if not path:
                raise ValueError("grid video_inputs item requires path/video/input or source=current")
            source = dict(item)
            source["path"] = str(Path(path)) if source_name not in {"current", "working", "main"} else str(path)
            sources.append(source)
        return sources

    raw_videos = params.get("videos", [])
    if not isinstance(raw_videos, list):
        raise ValueError("grid expects videos as a list")
    sources = [{"path": str(Path(item))} for item in raw_videos]
    if bool(params.get("include_current", True)):
        sources.insert(0, {"path": resolve_working_video(context)})
    return sources
