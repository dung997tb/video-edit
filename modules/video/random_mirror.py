from __future__ import annotations

import math
import random

from core.process import SubprocessExecutionError
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, probe_duration, resolve_working_video, run_ffmpeg, working_video_result


@register
class RandomMirrorModule(BaseModule):
    NAME = "random_mirror"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services):
        input_video = resolve_working_video(context)
        duration = probe_duration(input_video, context, services)
        segment_duration = max(0.1, float(self.params.get("segment_duration", 3.0)))
        flip_probability = min(1.0, max(0.0, float(self.params.get("flip_probability", 0.4))))
        seed = self.params.get("seed")
        rng = random.Random(seed) if seed is not None else random.Random()
        n_segments = max(1, math.ceil(duration / segment_duration))
        segments = []
        for index in range(n_segments):
            start = index * segment_duration
            end = min(duration, start + segment_duration)
            segments.append((start, end, rng.random() < flip_probability))
        output_path = operation_output_path(context, self.params, self.NAME)
        try:
            _run_with_audio(input_video, str(output_path), segments, context, services, crf=self.params.get("crf", 23))
        except SubprocessExecutionError:
            _run_video_only(input_video, str(output_path), segments, context, services, crf=self.params.get("crf", 23))
        return working_video_result(output_path)


def _run_with_audio(input_video: str, output_path: str, segments, context, services, *, crf) -> None:
    parts = []
    labels = []
    for index, (start, end, flip) in enumerate(segments):
        video_filters = f"trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS"
        if flip:
            video_filters += ",hflip"
        parts.append(f"[0:v]{video_filters}[v{index}]")
        parts.append(f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{index}]")
        labels.append(f"[v{index}][a{index}]")
    parts.append("".join(labels) + f"concat=n={len(segments)}:v=1:a=1[outv][outa]")
    run_ffmpeg(
        context,
        services,
        [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            input_video,
            "-filter_complex",
            ";".join(parts),
            "-map",
            "[outv]",
            "-map",
            "[outa]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(crf),
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            output_path,
        ],
    )


def _run_video_only(input_video: str, output_path: str, segments, context, services, *, crf) -> None:
    parts = []
    labels = []
    for index, (start, end, flip) in enumerate(segments):
        video_filters = f"trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS"
        if flip:
            video_filters += ",hflip"
        parts.append(f"[0:v]{video_filters}[v{index}]")
        labels.append(f"[v{index}]")
    parts.append("".join(labels) + f"concat=n={len(segments)}:v=1:a=0[outv]")
    run_ffmpeg(
        context,
        services,
        [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            input_video,
            "-filter_complex",
            ";".join(parts),
            "-map",
            "[outv]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(crf),
            "-movflags",
            "+faststart",
            output_path,
        ],
    )
