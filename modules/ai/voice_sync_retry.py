from __future__ import annotations

import json
import math

from core.cache import stable_value_signature
from core.models import StepResult
from modules.ai.segmenter import SegmenterModule
from modules.ai.tts import TTSModule
from modules.ai.voice_sync import VoiceSyncModule
from modules.base import BaseModule
from modules.registry import register


def _namespace_artifacts(prefix: str, artifacts: dict[str, str | list[str]]) -> dict[str, str | list[str]]:
    return {f"{prefix}_{key}": value for key, value in artifacts.items()}


def _split_segment_equally(segment: dict, parts: int) -> list[dict]:
    if parts <= 1:
        return [dict(segment)]
    text = str(segment.get("text", "")).strip()
    words = text.split()
    if len(words) <= 1:
        return [dict(segment)]
    parts = max(1, min(parts, len(words)))
    start = float(segment.get("start", 0.0))
    end = float(segment.get("end", start))
    duration = max(end - start, 0.0)
    if duration <= 0:
        return [dict(segment)]

    base = len(words) // parts
    remainder = len(words) % parts
    chunks: list[list[str]] = []
    cursor = 0
    for idx in range(parts):
        size = base + (1 if idx < remainder else 0)
        if size <= 0:
            continue
        next_cursor = min(len(words), cursor + size)
        chunk_words = words[cursor:next_cursor]
        if chunk_words:
            chunks.append(chunk_words)
        cursor = next_cursor
    if len(chunks) <= 1:
        return [dict(segment)]

    split_segments: list[dict] = []
    part_count = len(chunks)
    for idx, chunk_words in enumerate(chunks):
        chunk_start = start + (duration * idx / part_count)
        chunk_end = end if idx == part_count - 1 else start + (duration * (idx + 1) / part_count)
        split_segment = dict(segment)
        split_segment["text"] = " ".join(chunk_words).strip()
        split_segment["start"] = chunk_start
        split_segment["end"] = max(chunk_end, chunk_start)
        split_segments.append(split_segment)
    return split_segments


def _estimate_split_parts(overflow_item: dict, *, max_parts: int) -> int:
    source_duration = float(overflow_item.get("source_duration", 0.0) or 0.0)
    output_duration = float(overflow_item.get("output_duration", 0.0) or 0.0)
    dropped_duration = float(overflow_item.get("dropped_source_duration", 0.0) or 0.0)
    ratio = source_duration / max(output_duration, 0.001) if source_duration > 0 else 1.0
    parts = int(math.ceil(max(1.0, ratio)))
    if dropped_duration > 0:
        parts += 1
    return max(2, min(max_parts, parts))


def _resplit_overflow_segments(
    segments: list[dict],
    overflow_items: list[dict],
    *,
    max_parts: int,
) -> tuple[list[dict], bool]:
    overflow_by_index: dict[int, dict] = {}
    for item in overflow_items:
        dropped = float(item.get("dropped_source_duration", 0.0) or 0.0)
        if dropped <= 0:
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        overflow_by_index[index] = item
    if not overflow_by_index:
        return [dict(segment) for segment in segments], False

    changed = False
    rebuilt: list[dict] = []
    next_id = 1
    for segment_index, segment in enumerate(segments, start=1):
        overflow_item = overflow_by_index.get(segment_index)
        if overflow_item is None:
            clone = dict(segment)
            clone["id"] = next_id
            next_id += 1
            rebuilt.append(clone)
            continue
        split_parts = _estimate_split_parts(overflow_item, max_parts=max_parts)
        split_segments = _split_segment_equally(segment, split_parts)
        if len(split_segments) > 1:
            changed = True
        for split_segment in split_segments:
            split_segment["id"] = next_id
            next_id += 1
            rebuilt.append(split_segment)
    return rebuilt, changed


@register
class VoiceSyncRetryModule(BaseModule):
    NAME = "voice_sync_retry"

    def cache_inputs(self, context) -> dict:
        return {
            "retry_on_overflow": self.params.get("retry_on_overflow", True),
            "tighten_factor": self.params.get("tighten_factor", 0.85),
            "segment_strategy": self.params.get("segment_strategy", "slot_adaptive"),
            "segment_max_chars": self.params.get("segment_max_chars", 80),
            "segment_chars_per_second": self.params.get("segment_chars_per_second", 14.0),
            "resplit_on_unresolved": self.params.get("resplit_on_unresolved", True),
            "max_resplit_parts": self.params.get("max_resplit_parts", 4),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {
            "overflow_segments": stable_value_signature(
                {"voice_sync_overflow_segments": context.metadata.get("voice_sync_overflow_segments", [])}
            ),
            "translated_segments": stable_value_signature({"translated_segments": context.translated_segments}),
        }

    def execute(self, context, services) -> StepResult:
        retry_on_overflow = bool(self.params.get("retry_on_overflow", True))
        current_overflow = context.metadata.get("voice_sync_overflow_segments", [])
        if not retry_on_overflow:
            return StepResult(
                context_patch={
                    "metadata": {
                        "segment_retry_applied": False,
                        "segment_resplit_applied": False,
                        "overflow_unresolved": bool(current_overflow),
                    }
                }
            )
        if not current_overflow:
            return StepResult(
                context_patch={
                    "metadata": {
                        "segment_retry_applied": False,
                        "segment_resplit_applied": False,
                        "overflow_unresolved": False,
                    }
                }
            )

        tighten_factor = float(self.params.get("tighten_factor", 0.85))
        tighten_factor = min(max(tighten_factor, 0.1), 1.0)
        base_cps = float(
            context.state.get(
                "segment_chars_per_second",
                self.params.get("segment_chars_per_second", 14.0),
            )
        )
        retry_cps = max(4.0, base_cps * tighten_factor)
        segment_max_chars = int(
            context.state.get(
                "segment_max_chars",
                self.params.get("segment_max_chars", 80),
            )
        )
        segment_strategy = str(
            context.state.get(
                "segment_strategy",
                self.params.get("segment_strategy", "slot_adaptive"),
            )
        )

        segmenter_result = SegmenterModule(
            params={
                "strategy": segment_strategy,
                "max_chars": segment_max_chars,
                "chars_per_second": retry_cps,
            }
        ).execute(context, services)
        context.update(segmenter_result.context_patch)

        tts_result = TTSModule(
            params={
                "voice": context.state.get("tts_voice", services.settings.tts_default_voice),
                "rate": context.state.get("tts_rate", services.settings.tts_rate),
                "volume": context.state.get("tts_volume", services.settings.tts_volume),
            }
        ).execute(context, services)
        context.update(tts_result.context_patch)

        sync_result = VoiceSyncModule(
            params={
                "max_audio_stretch": context.state.get("max_audio_stretch", services.settings.max_audio_stretch),
            }
        ).execute(context, services)
        context.update(sync_result.context_patch)

        unresolved = bool(context.metadata.get("voice_sync_overflow_segments"))
        resplit_applied = False
        resplit_artifact_path: str | None = None
        resplit_tts_result: StepResult | None = None
        resplit_sync_result: StepResult | None = None
        if unresolved and bool(self.params.get("resplit_on_unresolved", True)):
            resplit_segments, resplit_applied = _resplit_overflow_segments(
                context.translated_segments or [],
                context.metadata.get("voice_sync_overflow_segments", []),
                max_parts=max(2, int(self.params.get("max_resplit_parts", 4))),
            )
            if resplit_applied:
                context.update({"translated_segments": resplit_segments})
                resplit_manifest_path = context.file_manager.temp("03c_resplit_segments.json")
                resplit_manifest_path.write_text(
                    json.dumps({"segments": resplit_segments}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                resplit_artifact_path = str(resplit_manifest_path)
                resplit_tts_result = TTSModule(
                    params={
                        "voice": context.state.get("tts_voice", services.settings.tts_default_voice),
                        "rate": context.state.get("tts_rate", services.settings.tts_rate),
                        "volume": context.state.get("tts_volume", services.settings.tts_volume),
                    }
                ).execute(context, services)
                context.update(resplit_tts_result.context_patch)
                resplit_sync_result = VoiceSyncModule(
                    params={
                        "max_audio_stretch": context.state.get("max_audio_stretch", services.settings.max_audio_stretch),
                    }
                ).execute(context, services)
                context.update(resplit_sync_result.context_patch)
                unresolved = bool(context.metadata.get("voice_sync_overflow_segments"))

        retry_artifacts: dict[str, str | list[str]] = {}
        retry_artifacts.update(_namespace_artifacts("retry_segmenter", segmenter_result.artifacts))
        retry_artifacts.update(_namespace_artifacts("retry_tts", tts_result.artifacts))
        retry_artifacts.update(_namespace_artifacts("retry_sync", sync_result.artifacts))
        if resplit_artifact_path:
            retry_artifacts["retry_resplit_segments"] = resplit_artifact_path
        if resplit_tts_result is not None:
            retry_artifacts.update(_namespace_artifacts("retry_resplit_tts", resplit_tts_result.artifacts))
        if resplit_sync_result is not None:
            retry_artifacts.update(_namespace_artifacts("retry_resplit_sync", resplit_sync_result.artifacts))
        if context.synced_audio:
            retry_artifacts["synced_audio"] = context.synced_audio
        return StepResult(
            context_patch={
                "synced_audio": context.synced_audio,
                "metadata": {
                    "segment_retry_applied": True,
                    "segment_retry_cps": retry_cps,
                    "segment_resplit_applied": resplit_applied,
                    "overflow_unresolved": unresolved,
                },
            },
            artifacts=retry_artifacts,
        )
