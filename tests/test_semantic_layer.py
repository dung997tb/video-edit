from __future__ import annotations

import unittest

from core.semantic import HookDetector, PacingAnalyzer, SilenceDetector


class SemanticLayerTests(unittest.TestCase):
    def test_silence_detector_finds_transcript_gaps(self) -> None:
        gaps = SilenceDetector(min_silence_duration=0.5).analyze(
            [
                {"start": 0.0, "end": 1.0, "text": "hello"},
                {"start": 2.0, "end": 3.0, "text": "world"},
            ]
        )

        self.assertEqual(gaps, [(1.0, 2.0)])

    def test_pacing_analyzer_returns_recommendation(self) -> None:
        result = PacingAnalyzer(target_words_per_minute=120).analyze(
            [{"start": 0.0, "end": 10.0, "text": "one two three four"}]
        )

        self.assertIn(result["recommendation"], {"tighten", "ok", "slow_down"})

    def test_hook_detector_prefers_hook_text(self) -> None:
        result = HookDetector().analyze(
            [
                {"start": 0.0, "end": 2.0, "text": "hello"},
                {"start": 3.0, "end": 5.0, "text": "why this mistake matters?"},
            ]
        )

        self.assertEqual(result["start"], 3.0)
