from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SilenceDetector:
    threshold_db: float = -40.0
    min_silence_duration: float = 0.5

    def analyze(self, segments: list[dict[str, Any]]) -> list[tuple[float, float]]:
        if not segments:
            return []
        gaps: list[tuple[float, float]] = []
        ordered = sorted(segments, key=lambda item: float(item.get("start", 0.0)))
        previous_end = float(ordered[0].get("end", 0.0))
        for segment in ordered[1:]:
            start = float(segment.get("start", previous_end))
            if start - previous_end >= self.min_silence_duration:
                gaps.append((previous_end, start))
            previous_end = max(previous_end, float(segment.get("end", previous_end)))
        return gaps


@dataclass(slots=True)
class PacingAnalyzer:
    target_words_per_minute: float = 150.0

    def analyze(self, segments: list[dict[str, Any]]) -> dict[str, Any]:
        words = sum(len(_words(str(segment.get("text", ""))) or []) for segment in segments)
        if not segments:
            return {"words_per_minute": 0.0, "recommendation": "unknown"}
        duration = max(float(segments[-1].get("end", 0.0)) - float(segments[0].get("start", 0.0)), 0.001)
        wpm = words / duration * 60.0
        if wpm < self.target_words_per_minute * 0.75:
            recommendation = "tighten"
        elif wpm > self.target_words_per_minute * 1.35:
            recommendation = "slow_down"
        else:
            recommendation = "ok"
        return {"words_per_minute": round(wpm, 2), "recommendation": recommendation}


@dataclass(slots=True)
class HookDetector:
    window_seconds: float = 30.0

    def analyze(self, segments: list[dict[str, Any]]) -> dict[str, Any]:
        candidates = [
            segment
            for segment in segments
            if float(segment.get("start", 0.0)) <= self.window_seconds and _hook_score(str(segment.get("text", ""))) > 0
        ]
        if not candidates:
            return {"start": 0.0, "end": min(self.window_seconds, float(segments[-1].get("end", 0.0))) if segments else 0.0}
        best = max(candidates, key=lambda item: _hook_score(str(item.get("text", ""))))
        return {"start": float(best.get("start", 0.0)), "end": float(best.get("end", self.window_seconds))}


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text, flags=re.UNICODE)


def _hook_score(text: str) -> int:
    lowered = text.lower()
    keywords = ("why", "how", "secret", "mistake", "stop", "watch", "đừng", "bí mật", "sai lầm", "tại sao")
    return sum(1 for keyword in keywords if keyword in lowered) + text.count("?")
