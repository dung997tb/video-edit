from __future__ import annotations

from pathlib import Path
from typing import Any

from core.ffmpeg_filters import atempo_chain
from core.models import StepResult
from core.process import run_subprocess


def resolve_working_video(context: Any) -> str:
    return str(context.state.get("working_video") or context.input_video)


def resolve_operation_index(params: dict[str, Any]) -> int:
    try:
        return max(1, int(params.get("op_index", 1)))
    except (TypeError, ValueError):
        return 1


def operation_output_path(context: Any, params: dict[str, Any], operation_name: str) -> Path:
    index = resolve_operation_index(params)
    return context.file_manager.temp(f"{index:02d}_{operation_name}.mp4")


def run_ffmpeg(context: Any, services: Any, command: list[str]) -> None:
    run_subprocess(
        command,
        job_id=context.job_id,
        job_manager=services.job_manager,
        process_registry=services.process_registry,
        cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
        grace_seconds=services.settings.cancel_grace_seconds,
    )


def working_video_result(output_path: Path) -> StepResult:
    output = str(output_path)
    return StepResult(
        context_patch={"state": {"working_video": output}},
        artifacts={"working_video": output},
    )


def probe_duration(path: str, context: Any, services: Any) -> float:
    result = run_subprocess(
        [
            services.settings.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        job_id=context.job_id,
        job_manager=services.job_manager,
        process_registry=services.process_registry,
        cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
        grace_seconds=services.settings.cancel_grace_seconds,
        timeout=30,
    )
    return float(result.stdout.strip())


def has_audio_stream(path: str, context: Any, services: Any) -> bool:
    result = run_subprocess(
        [
            services.settings.ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            path,
        ],
        job_id=context.job_id,
        job_manager=services.job_manager,
        process_registry=services.process_registry,
        cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
        grace_seconds=services.settings.cancel_grace_seconds,
        timeout=30,
    )
    return bool(result.stdout.strip())


def normalize_for_compose(
    path: str,
    target_w: int,
    target_h: int,
    *,
    fps: int = 30,
    input_start: float | None = None,
    input_end: float | None = None,
    input_duration: float | None = None,
    loop_to_duration: float | None = None,
    context: Any,
    services: Any,
    label: str = "compose",
) -> str:
    output_path = context.file_manager.temp(f"{label}_{target_w}x{target_h}_{fps}.mp4")
    vf = (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,"
        "setsar=1"
    )
    command = [services.settings.ffmpeg_path, "-y"]
    if loop_to_duration is not None:
        command.extend(["-stream_loop", "-1"])
    command.extend(["-i", path])
    if input_start is not None:
        command.extend(["-ss", f"{float(input_start):.3f}"])
    duration = _resolved_duration(input_start=input_start, input_end=input_end, input_duration=input_duration)
    if duration is not None and loop_to_duration is None:
        command.extend(["-t", f"{duration:.3f}"])
    if loop_to_duration is not None:
        command.extend(["-t", f"{float(loop_to_duration):.3f}"])
    command.extend(
        [
            "-vf",
            vf,
            "-r",
            str(fps),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    run_ffmpeg(context, services, command)
    return str(output_path)


def align_compose_clips(
    paths: list[str],
    *,
    duration_mode: str = "hold_last",
    context: Any,
    services: Any,
    label: str = "compose",
) -> list[str]:
    if not paths:
        return []
    mode = normalize_duration_mode(duration_mode)
    durations = [probe_duration(path, context, services) for path in paths]
    if mode in {"trim", "shortest"}:
        target = min(durations)
    else:
        target = max(durations)
    aligned: list[str] = []
    for index, path in enumerate(paths):
        clip_duration = durations[index]
        item_label = f"{label}_{index}"
        if mode == "loop" and clip_duration < target - 0.05:
            aligned.append(loop_video_to_duration(path, target, context=context, services=services, label=item_label))
        elif mode in {"hold_last", "pad_black"} and clip_duration < target - 0.05:
            aligned.append(
                pad_video_to_duration(
                    path,
                    target,
                    mode="black" if mode == "pad_black" else "clone",
                    context=context,
                    services=services,
                    label=item_label,
                )
            )
        elif mode in {"trim", "shortest"} and clip_duration > target + 0.05:
            aligned.append(trim_video_to_duration(path, target, context=context, services=services, label=item_label))
        else:
            aligned.append(path)
    return aligned


def normalize_duration_mode(value: str | None) -> str:
    mode = str(value or "hold_last").strip().lower()
    aliases = {
        "pad": "pad_black",
        "black": "pad_black",
        "pad_clone": "hold_last",
        "clone": "hold_last",
    }
    mode = aliases.get(mode, mode)
    allowed = {"hold_last", "loop", "trim", "shortest", "pad_black"}
    if mode not in allowed:
        raise ValueError(f"unsupported duration_mode '{value}'. supported: {', '.join(sorted(allowed))}")
    return mode


def trim_video_to_duration(
    path: str,
    duration: float,
    *,
    context: Any,
    services: Any,
    label: str = "trimmed",
) -> str:
    output_path = context.file_manager.temp(f"{label}_trimmed.mp4")
    run_ffmpeg(
        context,
        services,
        [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            path,
            "-t",
            f"{max(float(duration), 0.05):.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
    )
    return str(output_path)


def loop_video_to_duration(
    path: str,
    duration: float,
    *,
    context: Any,
    services: Any,
    label: str = "looped",
) -> str:
    source = ensure_audio_stream(path, probe_duration(path, context, services), context=context, services=services, label=label)
    output_path = context.file_manager.temp(f"{label}_looped.mp4")
    run_ffmpeg(
        context,
        services,
        [
            services.settings.ffmpeg_path,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            source,
            "-t",
            f"{max(float(duration), 0.05):.3f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
    )
    return str(output_path)


def pad_video_to_duration(
    path: str,
    duration: float,
    *,
    mode: str = "clone",
    context: Any,
    services: Any,
    label: str = "padded",
) -> str:
    current_duration = probe_duration(path, context, services)
    pad_duration = max(float(duration) - current_duration, 0.0)
    if pad_duration <= 0.05:
        return path
    source = ensure_audio_stream(path, current_duration, context=context, services=services, label=label)
    output_path = context.file_manager.temp(f"{label}_padded.mp4")
    if mode == "black":
        video_filter = f"tpad=stop_mode=add:color=black:stop_duration={pad_duration:.3f}"
    else:
        video_filter = f"tpad=stop_mode=clone:stop_duration={pad_duration:.3f}"
    filter_graph = f"[0:v]{video_filter}[v];[0:a]apad=pad_dur={pad_duration:.3f}[a]"
    run_ffmpeg(
        context,
        services,
        [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            source,
            "-filter_complex",
            filter_graph,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            f"{max(float(duration), 0.05):.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
    )
    return str(output_path)


def _resolved_duration(
    *,
    input_start: float | None,
    input_end: float | None,
    input_duration: float | None,
) -> float | None:
    if input_duration is not None:
        return max(float(input_duration), 0.001)
    if input_start is not None and input_end is not None:
        return max(float(input_end) - float(input_start), 0.001)
    return None


def ensure_audio_stream(
    path: str,
    duration: float | None = None,
    *,
    context: Any,
    services: Any,
    label: str = "with_audio",
) -> str:
    if has_audio_stream(path, context, services):
        return path
    duration = duration if duration is not None else probe_duration(path, context, services)
    output_path = context.file_manager.temp(f"{label}_audio.mp4")
    run_ffmpeg(
        context,
        services,
        [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            path,
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout=stereo:sample_rate=44100:d={duration:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ],
    )
    return str(output_path)

