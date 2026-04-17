from __future__ import annotations

import json
import unittest

from core.cache import make_step_cache_key
from core.context import PipelineContext
from core.file_manager import FileManager
from modules.ai.subtitle_gen import SubtitleModule
from modules.ai.translator import TranslatorModule
from modules.ai.voice_sync import VoiceSyncModule
from tests.helpers import make_services, make_test_root


def make_context(name: str) -> tuple[PipelineContext, object]:
    root = make_test_root(name)
    services = make_services(root)
    file_manager = FileManager(root / "temp", root / "output", "job-1")
    file_manager.ensure_dirs()
    context = PipelineContext(
        job_id="job-1",
        pipeline_type="dubbing",
        input_video=str(root / "input.mp4"),
        source_sha256="source-hash",
        file_manager=file_manager,
        artifact_store=services.artifact_store,
    )
    return context, services


class CacheInvalidationTests(unittest.TestCase):
    def test_step_cache_key_changes_when_upstream_file_contents_change(self) -> None:
        root = make_test_root("step-cache-file-hash")
        artifact = root / "artifact.wav"
        artifact.write_text("first", encoding="utf-8")

        key_a = make_step_cache_key(
            job_id="job-1",
            step_name="transcript",
            params={},
            upstream_artifact_hashes={"audio_path": str(artifact)},
            cache_version="v1",
        )

        artifact.write_text("second", encoding="utf-8")
        key_b = make_step_cache_key(
            job_id="job-1",
            step_name="transcript",
            params={},
            upstream_artifact_hashes={"audio_path": str(artifact)},
            cache_version="v1",
        )

        self.assertNotEqual(key_a, key_b)

    def test_subtitle_upstream_hash_changes_when_text_changes_with_same_count(self) -> None:
        context, _services = make_context("subtitle-upstream-hash")
        module = SubtitleModule()
        context.translated_segments = [{"id": 1, "start": 0.0, "end": 1.0, "text": "hello"}]

        hash_a = module.upstream_artifact_hashes(context)
        context.translated_segments = [{"id": 1, "start": 0.0, "end": 1.0, "text": "goodbye"}]
        hash_b = module.upstream_artifact_hashes(context)

        self.assertNotEqual(hash_a, hash_b)

    def test_voice_sync_upstream_hash_changes_when_timing_changes(self) -> None:
        context, _services = make_context("voice-sync-upstream-hash")
        wav_path = context.file_manager.step_file("tts", n=1)
        wav_path.write_text("fake-audio", encoding="utf-8")
        module = VoiceSyncModule()
        context.tts_segments = [{"index": 1, "start": 0.0, "end": 1.0, "text": "hello", "path": str(wav_path)}]

        hash_a = module.upstream_artifact_hashes(context)
        context.tts_segments = [{"index": 1, "start": 0.5, "end": 1.5, "text": "hello", "path": str(wav_path)}]
        hash_b = module.upstream_artifact_hashes(context)

        self.assertNotEqual(hash_a, hash_b)

    def test_translator_operation_cache_uses_transcript_contents(self) -> None:
        context, services = make_context("translator-cache")
        transcript_path = context.file_manager.step_file("transcript")
        module = TranslatorModule(params={"service": "google", "source_language": "en", "target_language": "vi"})
        calls = {"count": 0}

        def build_translator(**_kwargs):
            calls["count"] += 1
            return lambda text: f"TR:{text}"

        module._build_translator = build_translator  # type: ignore[method-assign]

        context.metadata["detected_language"] = "en"
        context.state["target_language"] = "vi"
        context.segments = [{"id": 1, "start": 0.0, "end": 1.0, "text": "hello"}]
        transcript_path.write_text(
            json.dumps({"segments": context.segments}, ensure_ascii=False),
            encoding="utf-8",
        )
        context.transcript_path = str(transcript_path)

        first = module.execute(context, services)

        context.segments = [{"id": 1, "start": 0.0, "end": 1.0, "text": "goodbye"}]
        transcript_path.write_text(
            json.dumps({"segments": context.segments}, ensure_ascii=False),
            encoding="utf-8",
        )
        second = module.execute(context, services)

        self.assertEqual(calls["count"], 2)
        self.assertEqual(first.context_patch["translated_segments"][0]["text"], "TR:hello")
        self.assertEqual(second.context_patch["translated_segments"][0]["text"], "TR:goodbye")
