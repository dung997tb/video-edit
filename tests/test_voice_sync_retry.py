from __future__ import annotations

import unittest
from unittest.mock import patch

from core.context import PipelineContext
from core.file_manager import FileManager
from core.models import StepResult
from modules.ai.segmenter import SegmenterModule
from modules.ai.tts import TTSModule
from modules.ai.voice_sync import VoiceSyncModule
from modules.ai.voice_sync_retry import VoiceSyncRetryModule
from tests.helpers import make_services, make_test_root


def _build_context(name: str) -> tuple[PipelineContext, object]:
    root = make_test_root(name)
    services = make_services(root)
    file_manager = FileManager(root / "temp", root / "output", "job-retry")
    file_manager.ensure_dirs()
    context = PipelineContext(
        job_id="job-retry",
        pipeline_type="dubbing",
        input_video=str(root / "input.mp4"),
        source_sha256="source-hash",
        file_manager=file_manager,
        artifact_store=services.artifact_store,
        translated_segments=[{"id": 1, "start": 0.0, "end": 1.0, "text": "xin chao"}],
        metadata={},
        state={"segment_chars_per_second": 14.0},
    )
    return context, services


class VoiceSyncRetryTests(unittest.TestCase):
    def test_retry_not_applied_when_no_overflow(self) -> None:
        context, services = _build_context("retry-no-overflow")
        context.metadata["voice_sync_overflow_segments"] = []
        module = VoiceSyncRetryModule(params={"retry_on_overflow": True})

        result = module.execute(context, services)

        self.assertFalse(result.context_patch["metadata"]["segment_retry_applied"])
        self.assertFalse(result.context_patch["metadata"]["overflow_unresolved"])

    def test_retry_replays_segment_tts_and_sync_when_overflow_exists(self) -> None:
        context, services = _build_context("retry-overflow")
        context.metadata["voice_sync_overflow_segments"] = [
            {"index": 1, "dropped_source_duration": 0.5, "speed": 1.3}
        ]
        module = VoiceSyncRetryModule(
            params={
                "retry_on_overflow": True,
                "tighten_factor": 0.85,
                "segment_strategy": "slot_adaptive",
                "segment_max_chars": 80,
                "segment_chars_per_second": 14.0,
            }
        )

        with (
            patch.object(
                SegmenterModule,
                "execute",
                return_value=StepResult(
                    context_patch={"translated_segments": context.translated_segments},
                    artifacts={"segmenter": "03b_segmented.json"},
                ),
            ) as segmenter_exec,
            patch.object(
                TTSModule,
                "execute",
                return_value=StepResult(
                    context_patch={
                        "tts_segments": [{"index": 1, "start": 0.0, "end": 1.0, "text": "xin chao", "path": "tts.wav"}]
                    },
                    artifacts={"tts_segments": ["tts.wav"]},
                ),
            ) as tts_exec,
            patch.object(
                VoiceSyncModule,
                "execute",
                return_value=StepResult(
                    context_patch={
                        "synced_audio": "synced.wav",
                        "metadata": {
                            "voice_sync_overflow_segments": [],
                            "overflow_unresolved": False,
                        },
                    },
                    artifacts={"synced_audio": "synced.wav"},
                ),
            ) as sync_exec,
        ):
            result = module.execute(context, services)

        segmenter_exec.assert_called_once()
        tts_exec.assert_called_once()
        sync_exec.assert_called_once()
        self.assertTrue(result.context_patch["metadata"]["segment_retry_applied"])
        self.assertFalse(result.context_patch["metadata"]["segment_resplit_applied"])
        self.assertFalse(result.context_patch["metadata"]["overflow_unresolved"])
        self.assertEqual(result.artifacts["synced_audio"], "synced.wav")

    def test_retry_applies_resplit_when_overflow_still_unresolved(self) -> None:
        context, services = _build_context("retry-overflow-resplit")
        context.metadata["voice_sync_overflow_segments"] = [
            {"index": 1, "dropped_source_duration": 0.5, "speed": 1.3}
        ]
        context.translated_segments = [
            {"id": 1, "start": 0.0, "end": 1.0, "text": "xin chao ban than men"}
        ]
        module = VoiceSyncRetryModule(
            params={
                "retry_on_overflow": True,
                "tighten_factor": 0.85,
                "resplit_on_unresolved": True,
                "max_resplit_parts": 4,
            }
        )

        with (
            patch.object(
                SegmenterModule,
                "execute",
                return_value=StepResult(
                    context_patch={"translated_segments": context.translated_segments},
                    artifacts={"segmenter": "03b_segmented.json"},
                ),
            ),
            patch.object(
                TTSModule,
                "execute",
                side_effect=[
                    StepResult(
                        context_patch={
                            "tts_segments": [
                                {"index": 1, "start": 0.0, "end": 1.0, "text": "xin chao", "path": "tts1.wav"}
                            ]
                        },
                        artifacts={"tts_segments": ["tts1.wav"]},
                    ),
                    StepResult(
                        context_patch={
                            "tts_segments": [
                                {"index": 1, "start": 0.0, "end": 0.5, "text": "xin chao", "path": "tts2.wav"},
                                {"index": 2, "start": 0.5, "end": 1.0, "text": "ban than men", "path": "tts3.wav"},
                            ]
                        },
                        artifacts={"tts_segments": ["tts2.wav", "tts3.wav"]},
                    ),
                ],
            ) as tts_exec,
            patch.object(
                VoiceSyncModule,
                "execute",
                side_effect=[
                    StepResult(
                        context_patch={
                            "synced_audio": "synced-1.wav",
                            "metadata": {
                                "voice_sync_overflow_segments": [
                                    {
                                        "index": 1,
                                        "source_duration": 1.8,
                                        "output_duration": 1.0,
                                        "dropped_source_duration": 0.8,
                                    }
                                ],
                                "overflow_unresolved": True,
                            },
                        },
                        artifacts={"synced_audio": "synced-1.wav"},
                    ),
                    StepResult(
                        context_patch={
                            "synced_audio": "synced-2.wav",
                            "metadata": {
                                "voice_sync_overflow_segments": [],
                                "overflow_unresolved": False,
                            },
                        },
                        artifacts={"synced_audio": "synced-2.wav"},
                    ),
                ],
            ) as sync_exec,
        ):
            result = module.execute(context, services)

        self.assertEqual(tts_exec.call_count, 2)
        self.assertEqual(sync_exec.call_count, 2)
        self.assertTrue(result.context_patch["metadata"]["segment_retry_applied"])
        self.assertTrue(result.context_patch["metadata"]["segment_resplit_applied"])
        self.assertFalse(result.context_patch["metadata"]["overflow_unresolved"])
        self.assertEqual(result.context_patch["synced_audio"], "synced-2.wav")
        self.assertIn("retry_resplit_segments", result.artifacts)
