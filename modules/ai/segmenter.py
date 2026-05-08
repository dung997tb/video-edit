from __future__ import annotations

import json

from core.cache import stable_value_signature
from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register


MIN_SLOT_ADAPTIVE_CHARS = 8


def _split_text_by_length(text: str, max_chars: int) -> list[str]:
    words = text.split()
    if not words:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for word in words:
        projected = current_len + len(word) + (1 if current else 0)
        if current and projected > max_chars:
            chunks.append(" ".join(current))
            current = [word]
            current_len = len(word)
            continue
        current.append(word)
        current_len = projected
    if current:
        chunks.append(" ".join(current))
    return chunks or [text]


def _effective_max_chars_for_segment(
    *,
    start: float,
    end: float,
    strategy: str,
    max_chars: int,
    chars_per_second: float,
) -> int:
    if strategy == "slot_adaptive":
        duration = max(end - start, 0.0)
        slot_budget = int(round(max(duration, 0.25) * chars_per_second))
        return max(MIN_SLOT_ADAPTIVE_CHARS, min(max_chars, slot_budget))
    return max_chars


@register
class SegmenterModule(BaseModule):
    NAME = "segmenter"

    def cache_inputs(self, context) -> dict:
        return {
            "strategy": self.params.get("strategy", "chars"),
            "max_chars": self.params.get("max_chars", 80),
            "chars_per_second": self.params.get("chars_per_second", 14.0),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        source_segments = context.translated_segments or context.segments
        return {
            "segments": stable_value_signature({"segments": source_segments}),
        }

    def execute(self, context, services) -> StepResult:
        source_segments = context.translated_segments or context.segments
        if not source_segments:
            raise ValueError("segmenter requires source segments")
        strategy = str(self.params.get("strategy", "chars")).strip().lower()
        if strategy not in {"chars", "slot_adaptive"}:
            raise ValueError("segmenter strategy must be 'chars' or 'slot_adaptive'")
        max_chars = int(self.params.get("max_chars", 80))
        if max_chars <= 0:
            raise ValueError("segmenter max_chars must be > 0")
        chars_per_second = float(self.params.get("chars_per_second", 14.0))
        if chars_per_second <= 0:
            raise ValueError("segmenter chars_per_second must be > 0")

        segmented: list[dict] = []
        next_id = 1
        for segment in source_segments:
            text = str(segment.get("text", "")).strip()
            start = float(segment.get("start", 0.0))
            end = float(segment.get("end", start))
            effective_max_chars = _effective_max_chars_for_segment(
                start=start,
                end=end,
                strategy=strategy,
                max_chars=max_chars,
                chars_per_second=chars_per_second,
            )
            chunks = _split_text_by_length(text, effective_max_chars) if text else [""]
            duration = max(end - start, 0.0)
            if len(chunks) == 1:
                segmented.append(
                    {
                        **segment,
                        "id": next_id,
                        "text": chunks[0],
                        "start": start,
                        "end": end,
                    }
                )
                next_id += 1
                continue

            char_weights = [max(len(item), 1) for item in chunks]
            total_weight = sum(char_weights)
            cursor = start
            for index, chunk in enumerate(chunks):
                if index == len(chunks) - 1:
                    chunk_end = end
                else:
                    ratio = char_weights[index] / total_weight if total_weight else 1 / len(chunks)
                    chunk_end = min(end, cursor + duration * ratio)
                segmented.append(
                    {
                        **segment,
                        "id": next_id,
                        "text": chunk,
                        "start": cursor,
                        "end": max(chunk_end, cursor),
                    }
                )
                next_id += 1
                cursor = max(chunk_end, cursor)

        output_path = context.file_manager.temp("03b_segmented.json")
        output_path.write_text(
            json.dumps(
                {
                    "strategy": strategy,
                    "max_chars": max_chars,
                    "chars_per_second": chars_per_second,
                    "segments": segmented,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return StepResult(
            context_patch={"translated_segments": segmented},
            artifacts={"segmenter": str(output_path)},
        )
