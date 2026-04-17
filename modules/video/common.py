from __future__ import annotations

from pathlib import Path
from typing import Any

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


def atempo_chain(speed: float) -> list[str]:
    if speed <= 0:
        raise ValueError("speed factor must be > 0")
    if abs(speed - 1.0) < 1e-6:
        return ["atempo=1.0"]
    filters: list[str] = []
    remaining = speed
    while remaining > 2.0 + 1e-6:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5 - 1e-6:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}".rstrip("0").rstrip("."))
    return filters
