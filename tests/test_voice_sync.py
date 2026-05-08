import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules.ai.voice_sync import VoiceSyncModule, build_voice_filter_complex, plan_voice_segments


class VoiceSyncTests(unittest.TestCase):
    def test_cache_inputs_includes_max_audio_stretch_when_configured(self) -> None:
        module = VoiceSyncModule(params={"max_audio_stretch": 1.75})
        context = SimpleNamespace(state={})

        cache_inputs = module.cache_inputs(context)

        self.assertEqual(cache_inputs, {"max_audio_stretch": 1.75})

    def test_total_duration_uses_actual_tts_runtime(self) -> None:
        plans = plan_voice_segments(
            [
                {"index": 1, "start": 0.0, "end": 1.0, "path": "a.wav"},
                {"index": 2, "start": 2.0, "end": 3.0, "path": "b.wav"},
            ],
            resolve_duration=lambda segment: {"a.wav": 0.4, "b.wav": 0.6}[segment["path"]],
            max_audio_stretch=1.3,
        )

        self.assertAlmostEqual(max(plan.end_time for plan in plans), 2.6, places=3)

    def test_segment_can_use_gap_after_slot_without_speedup(self) -> None:
        plans = plan_voice_segments(
            [
                {"index": 1, "start": 0.0, "end": 1.0, "path": "a.wav"},
                {"index": 2, "start": 1.5, "end": 2.0, "path": "b.wav"},
            ],
            resolve_duration=lambda segment: {"a.wav": 1.4, "b.wav": 0.4}[segment["path"]],
            max_audio_stretch=1.3,
        )

        self.assertAlmostEqual(plans[0].speed, 1.0, places=3)
        self.assertIsNone(plans[0].trim_duration)
        self.assertAlmostEqual(plans[0].end_time, 1.4, places=3)

    def test_segment_speeds_up_when_overflow_is_within_limit(self) -> None:
        plans = plan_voice_segments(
            [
                {"index": 1, "start": 0.0, "end": 1.0, "path": "a.wav"},
                {"index": 2, "start": 1.0, "end": 2.0, "path": "b.wav"},
            ],
            resolve_duration=lambda segment: {"a.wav": 1.2, "b.wav": 0.4}[segment["path"]],
            max_audio_stretch=1.3,
        )

        self.assertAlmostEqual(plans[0].speed, 1.2, places=3)
        self.assertAlmostEqual(plans[0].trim_duration or 0.0, 1.0, places=3)
        filter_graph = build_voice_filter_complex(plans)
        self.assertIn("atempo=1.2", filter_graph)
        self.assertIn("atrim=duration=1.000", filter_graph)

    def test_segment_trims_when_overflow_exceeds_stretch_limit(self) -> None:
        plans = plan_voice_segments(
            [
                {"index": 1, "start": 0.0, "end": 1.0, "path": "a.wav"},
                {"index": 2, "start": 1.0, "end": 2.0, "path": "b.wav"},
            ],
            resolve_duration=lambda segment: {"a.wav": 2.0, "b.wav": 0.4}[segment["path"]],
            max_audio_stretch=1.3,
        )

        self.assertAlmostEqual(plans[0].speed, 1.3, places=3)
        self.assertAlmostEqual(plans[0].trim_duration or 0.0, 1.0, places=3)
        self.assertGreater(plans[0].dropped_source_duration, 0.0)

    def test_execute_sets_overflow_metadata(self) -> None:
        module = VoiceSyncModule(params={"max_audio_stretch": 1.3})
        context = SimpleNamespace(
            job_id="job-1",
            tts_segments=[
                {"index": 1, "start": 0.0, "end": 1.0, "path": "a.wav"},
                {"index": 2, "start": 1.0, "end": 2.0, "path": "b.wav"},
            ],
            file_manager=SimpleNamespace(step_file=lambda name: "synced.wav"),
            metadata={},
        )
        services = SimpleNamespace(
            settings=SimpleNamespace(
                ffmpeg_path="ffmpeg",
                ffprobe_path="ffprobe",
                max_audio_stretch=1.3,
                cancel_grace_seconds=0.1,
            ),
            job_manager=SimpleNamespace(is_cancel_requested=lambda job_id: False),
            process_registry=SimpleNamespace(),
        )

        with (
            patch.object(module, "_probe_duration", side_effect=[2.0, 0.5]),
            patch("modules.ai.voice_sync.run_subprocess"),
        ):
            result = module.execute(context, services)

        self.assertTrue(result.context_patch["metadata"]["overflow_unresolved"])
        self.assertGreater(len(result.context_patch["metadata"]["voice_sync_overflow_segments"]), 0)
