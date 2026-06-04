from __future__ import annotations

from dataclasses import dataclass

from core.cache import stable_value_signature
from core.models import StepResult
from core.process import run_subprocess
from modules.base import BaseModule
from modules.registry import register


MIN_SYNC_DURATION = 0.001
MAX_VOICE_SYNC_INPUTS_PER_COMMAND = 64
FILTER_SCRIPT_THRESHOLD = 4000


@dataclass(slots=True)
class VoiceSyncPlan:
    path: str
    start: float
    source_duration: float
    output_duration: float
    speed: float = 1.0
    trim_duration: float | None = None
    dropped_source_duration: float = 0.0
    mute: bool = False

    @property
    def end_time(self) -> float:
        return self.start + self.output_duration


def plan_voice_segments(
    segments: list[dict],
    *,
    resolve_duration,
    max_audio_stretch: float,
    min_output_duration: float = MIN_SYNC_DURATION,
) -> list[VoiceSyncPlan]:
    ordered_segments = sorted(
        segments,
        key=lambda item: (float(item.get("start", 0.0)), int(item.get("index", 0))),
    )
    stretch_limit = max(1.0, float(max_audio_stretch))
    plans: list[VoiceSyncPlan] = []
    for index, segment in enumerate(ordered_segments):
        start = max(float(segment.get("start", 0.0)), 0.0)
        source_duration = float(resolve_duration(segment) or 0.0)
        if source_duration <= 0:
            source_duration = max(float(segment.get("end", start)) - start, min_output_duration)
        next_start = None
        if index + 1 < len(ordered_segments):
            next_start = max(float(ordered_segments[index + 1].get("start", start)), start)

        output_duration = source_duration
        speed = 1.0
        trim_duration = None
        mute = False
        if next_start is not None:
            available_duration = max(next_start - start, 0.0)
            if available_duration <= 0:
                output_duration = min_output_duration
                trim_duration = min_output_duration
                dropped_source_duration = max(source_duration - min_output_duration, 0.0)
                mute = True
            elif source_duration > available_duration:
                required_speed = source_duration / available_duration
                if required_speed <= stretch_limit:
                    speed = required_speed
                else:
                    # Overflow is too large for the strict slot: apply max allowed
                    # speed before trim so we keep more spoken content than trim-only.
                    speed = stretch_limit
                trim_duration = available_duration
                output_duration = available_duration
                kept_source_duration = available_duration * speed
                dropped_source_duration = max(source_duration - kept_source_duration, 0.0)
            else:
                dropped_source_duration = 0.0
        else:
            dropped_source_duration = 0.0

        plans.append(
            VoiceSyncPlan(
                path=segment["path"],
                start=start,
                source_duration=source_duration,
                output_duration=max(output_duration, min_output_duration),
                speed=speed,
                trim_duration=trim_duration,
                dropped_source_duration=dropped_source_duration,
                mute=mute,
            )
        )
    return plans


def build_voice_filter_complex(plans: list[VoiceSyncPlan]) -> str:
    if not plans:
        return "[0:a]anull[out]"
    delayed_labels = []
    lines = []
    for index, plan in enumerate(plans, start=1):
        label = f"s{index}"
        start_ms = max(int(round(plan.start * 1000)), 0)
        filters: list[str] = []
        filters.extend(_build_atempo_filters(plan.speed))
        if plan.trim_duration is not None:
            filters.append(f"atrim=duration={plan.trim_duration:.3f}")
        if plan.mute:
            filters.append("volume=0")
        filters.append("asetpts=PTS-STARTPTS")
        filters.append(f"adelay={start_ms}|{start_ms}")
        lines.append(f"[{index}:a]{','.join(filters)}[{label}]")
        delayed_labels.append(f"[{label}]")
    inputs = "[0:a]" + "".join(delayed_labels)
    lines.append(f"{inputs}amix=inputs={len(delayed_labels) + 1}:duration=longest:normalize=0[out]")
    return ";".join(lines)


def _chunk_plans(plans: list[VoiceSyncPlan], chunk_size: int) -> list[list[VoiceSyncPlan]]:
    return [plans[index : index + chunk_size] for index in range(0, len(plans), chunk_size)]


def _build_atempo_filters(speed: float) -> list[str]:
    if abs(speed - 1.0) < 1e-6:
        return []
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


@register
class VoiceSyncModule(BaseModule):
    NAME = "synced_audio"

    def cache_inputs(self, context) -> dict:
        configured = self.params.get("max_audio_stretch", context.state.get("max_audio_stretch"))
        if configured is None:
            return {}
        return {"max_audio_stretch": float(configured)}

    def upstream_artifact_hashes(self, context) -> dict:
        return {
            "tts_segments": stable_value_signature({"tts_segments": context.tts_segments}),
        }

    def execute(self, context, services) -> StepResult:
        if not context.tts_segments:
            raise ValueError("tts_segments are required before voice sync")
        output_path = context.file_manager.step_file("synced_audio")
        plans = plan_voice_segments(
            context.tts_segments,
            resolve_duration=lambda segment: self._probe_duration(segment["path"], context, services),
            max_audio_stretch=float(self.params.get("max_audio_stretch", services.settings.max_audio_stretch)),
        )
        overflow_segments = [
            {
                "index": index,
                "path": plan.path,
                "start": plan.start,
                "output_duration": plan.output_duration,
                "source_duration": plan.source_duration,
                "speed": plan.speed,
                "dropped_source_duration": plan.dropped_source_duration,
            }
            for index, plan in enumerate(plans, start=1)
            if plan.dropped_source_duration > 0
        ]
        total_duration = max((plan.end_time for plan in plans), default=MIN_SYNC_DURATION)
        if len(plans) > MAX_VOICE_SYNC_INPUTS_PER_COMMAND:
            partial_paths = []
            for chunk_index, plan_chunk in enumerate(
                _chunk_plans(plans, MAX_VOICE_SYNC_INPUTS_PER_COMMAND),
                start=1,
            ):
                partial_path = context.file_manager.temp(f"06_synced_part_{chunk_index:03d}.wav")
                self._run_sync_command(plan_chunk, total_duration, partial_path, context, services)
                partial_paths.append(str(partial_path))
            self._mix_partial_outputs(partial_paths, output_path, context, services)
        else:
            self._run_sync_command(plans, total_duration, output_path, context, services)
        metadata_patch = {
            "voice_sync_overflow_segments": overflow_segments,
            "overflow_unresolved": bool(overflow_segments),
        }
        return StepResult(
            context_patch={"synced_audio": str(output_path), "metadata": metadata_patch},
            artifacts={"synced_audio": str(output_path)},
        )

    def _run_sync_command(self, plans: list[VoiceSyncPlan], total_duration: float, output_path, context, services) -> None:
        command = [
            services.settings.ffmpeg_path,
            "-y",
            "-f",
            "lavfi",
            "-t",
            f"{total_duration:.3f}",
            "-i",
            "anullsrc=r=24000:cl=mono",
        ]
        for plan in plans:
            command.extend(["-i", plan.path])
        filter_complex = build_voice_filter_complex(plans)
        if len(filter_complex) > FILTER_SCRIPT_THRESHOLD:
            filter_script_path = context.file_manager.temp("06_voice_sync_filter.txt")
            filter_script_path.write_text(filter_complex, encoding="utf-8")
            command.extend(["-filter_complex_script", str(filter_script_path)])
        else:
            command.extend(["-filter_complex", filter_complex])
        command.extend(
            [
                "-map",
                "[out]",
                str(output_path),
            ]
        )
        run_subprocess(
            command,
            job_id=context.job_id,
            job_manager=services.job_manager,
            process_registry=services.process_registry,
            cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
            grace_seconds=services.settings.cancel_grace_seconds,
        )

    def _mix_partial_outputs(self, partial_paths: list[str], output_path, context, services) -> None:
        if not partial_paths:
            raise ValueError("partial_paths are required before final voice mix")
        command = [services.settings.ffmpeg_path, "-y"]
        for path in partial_paths:
            command.extend(["-i", path])
        filter_complex = (
            "".join(f"[{index}:a]" for index in range(len(partial_paths)))
            + f"amix=inputs={len(partial_paths)}:duration=longest:normalize=0[out]"
        )
        command.extend(["-filter_complex", filter_complex, "-map", "[out]", str(output_path)])
        run_subprocess(
            command,
            job_id=context.job_id,
            job_manager=services.job_manager,
            process_registry=services.process_registry,
            cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
            grace_seconds=services.settings.cancel_grace_seconds,
        )

    def _probe_duration(self, audio_path: str, context, services) -> float:
        result = run_subprocess(
            [
                services.settings.ffprobe_path,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            job_id=context.job_id,
            job_manager=services.job_manager,
            process_registry=services.process_registry,
            cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
            grace_seconds=services.settings.cancel_grace_seconds,
            timeout=30,
        )
        try:
            return float(result.stdout.strip())
        except ValueError as exc:
            raise RuntimeError(f"unable to parse ffprobe duration for {audio_path}") from exc
