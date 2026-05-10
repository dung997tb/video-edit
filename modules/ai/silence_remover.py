from __future__ import annotations

import re

from core.models import StepResult
from core.process import SubprocessExecutionError, run_subprocess
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import probe_duration


_SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9.]+)")


@register
class SilenceRemoverModule(BaseModule):
    NAME = "silence_cut"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"source_sha256": context.source_sha256}

    def execute(self, context, services) -> StepResult:
        input_video = context.state.get("working_video") or context.input_video
        min_silence = float(self.params.get("min_silence_duration", self.params.get("duration", 0.5)))
        noise_db = float(self.params.get("silence_threshold_db", self.params.get("noise_db", -35)))
        padding = max(0.0, float(self.params.get("padding_ms", 80)) / 1000.0)
        duration = probe_duration(input_video, context, services)
        silences = _detect_silences(input_video, context, services, min_silence, noise_db)
        speech_segments = _speech_segments(duration, silences, padding=padding)
        output_path = context.file_manager.step_file("final")

        if not speech_segments:
            raise ValueError("silence_cut detected no speech segments to keep")

        if len(speech_segments) == 1 and speech_segments[0][0] <= 0.001 and speech_segments[0][1] >= duration - 0.001:
            _copy_video(input_video, str(output_path), context, services)
        else:
            _concat_segments(input_video, str(output_path), speech_segments, context, services, crf=self.params.get("crf", 23))

        metadata = dict(context.metadata)
        metadata["silence_cut"] = {
            "detected_silences": len(silences),
            "kept_segments": len(speech_segments),
            "input_duration": duration,
        }
        return StepResult(
            context_patch={
                "output_video": str(output_path),
                "metadata": metadata,
                "state": {"working_video": str(output_path)},
            },
            artifacts={"output_video": str(output_path)},
        )


def _detect_silences(path: str, context, services, min_silence: float, noise_db: float) -> list[tuple[float, float]]:
    result = run_subprocess(
        [
            services.settings.ffmpeg_path,
            "-hide_banner",
            "-i",
            path,
            "-af",
            f"silencedetect=n={noise_db:g}dB:d={min_silence:.3f}",
            "-f",
            "null",
            "-",
        ],
        job_id=context.job_id,
        job_manager=services.job_manager,
        process_registry=services.process_registry,
        cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
        grace_seconds=services.settings.cancel_grace_seconds,
    )
    starts: list[float] = []
    silences: list[tuple[float, float]] = []
    for line in result.stderr.splitlines():
        start_match = _SILENCE_START_RE.search(line)
        if start_match:
            starts.append(float(start_match.group(1)))
            continue
        end_match = _SILENCE_END_RE.search(line)
        if end_match and starts:
            silences.append((starts.pop(0), float(end_match.group(1))))
    return silences


def _speech_segments(
    duration: float,
    silences: list[tuple[float, float]],
    *,
    padding: float,
) -> list[tuple[float, float]]:
    segments: list[tuple[float, float]] = []
    cursor = 0.0
    for silence_start, silence_end in sorted(silences):
        keep_end = max(cursor, silence_start + padding)
        if keep_end - cursor >= 0.05:
            segments.append((cursor, min(keep_end, duration)))
        cursor = min(duration, max(cursor, silence_end - padding))
    if duration - cursor >= 0.05:
        segments.append((cursor, duration))
    return [(start, end) for start, end in segments if end - start >= 0.05]


def _copy_video(input_video: str, output_path: str, context, services) -> None:
    run_subprocess(
        [services.settings.ffmpeg_path, "-y", "-i", input_video, "-c", "copy", output_path],
        job_id=context.job_id,
        job_manager=services.job_manager,
        process_registry=services.process_registry,
        cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
        grace_seconds=services.settings.cancel_grace_seconds,
    )


def _concat_segments(input_video: str, output_path: str, segments: list[tuple[float, float]], context, services, *, crf) -> None:
    filter_parts = []
    labels = []
    for index, (start, end) in enumerate(segments):
        filter_parts.append(f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{index}]")
        filter_parts.append(f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{index}]")
        labels.append(f"[v{index}][a{index}]")
    filter_parts.append("".join(labels) + f"concat=n={len(segments)}:v=1:a=1[outv][outa]")
    command = [
        services.settings.ffmpeg_path,
        "-y",
        "-i",
        input_video,
        "-filter_complex",
        ";".join(filter_parts),
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
    ]
    try:
        run_subprocess(
            command,
            job_id=context.job_id,
            job_manager=services.job_manager,
            process_registry=services.process_registry,
            cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
            grace_seconds=services.settings.cancel_grace_seconds,
        )
    except SubprocessExecutionError:
        filter_parts = []
        labels = []
        for index, (start, end) in enumerate(segments):
            filter_parts.append(f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{index}]")
            labels.append(f"[v{index}]")
        filter_parts.append("".join(labels) + f"concat=n={len(segments)}:v=1:a=0[outv]")
        run_subprocess(
            [
                services.settings.ffmpeg_path,
                "-y",
                "-i",
                input_video,
                "-filter_complex",
                ";".join(filter_parts),
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
            job_id=context.job_id,
            job_manager=services.job_manager,
            process_registry=services.process_registry,
            cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
            grace_seconds=services.settings.cancel_grace_seconds,
        )
