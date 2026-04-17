import unittest

from core.cache import CacheManager, make_operation_cache_key, make_step_cache_key
from core.file_manager import FileManager
from tests.helpers import make_test_root
from core.artifact_store import LocalArtifactStore


class CacheKeyTests(unittest.TestCase):
    def test_operation_cache_key_changes_with_language_and_voice(self) -> None:
        key_a = make_operation_cache_key(
            source_sha256="video-hash",
            operation="tts",
            model="edge-tts",
            language="vi",
            params={"voice": "voice-a", "rate": "+0%"},
            cache_version="v1",
        )
        key_b = make_operation_cache_key(
            source_sha256="video-hash",
            operation="tts",
            model="edge-tts",
            language="vi",
            params={"voice": "voice-b", "rate": "+0%"},
            cache_version="v1",
        )
        key_c = make_operation_cache_key(
            source_sha256="video-hash",
            operation="tts",
            model="edge-tts",
            language="en",
            params={"voice": "voice-a", "rate": "+0%"},
            cache_version="v1",
        )
        self.assertNotEqual(key_a, key_b)
        self.assertNotEqual(key_a, key_c)

    def test_step_cache_key_changes_with_upstream_hashes(self) -> None:
        key_a = make_step_cache_key(
            job_id="job-1",
            step_name="translate",
            params={"target_language": "vi"},
            upstream_artifact_hashes={"transcript_sha256": "aaa"},
            cache_version="v1",
        )
        key_b = make_step_cache_key(
            job_id="job-1",
            step_name="translate",
            params={"target_language": "vi"},
            upstream_artifact_hashes={"transcript_sha256": "bbb"},
            cache_version="v1",
        )
        self.assertNotEqual(key_a, key_b)

    def test_operation_bundle_round_trip_restores_artifacts(self) -> None:
        root = make_test_root("cache-bundle")
        file_manager = FileManager(root / "temp", root / "output", "job-cache")
        file_manager.ensure_dirs()
        artifact_store = LocalArtifactStore(root / "shared-artifacts")
        cache_manager = CacheManager(artifact_store=artifact_store, cache_version="v1")
        audio_path = file_manager.step_file("tts", n=1)
        audio_path.write_text("audio-bytes", encoding="utf-8")

        cache_manager.save_operation_bundle(
            operation="tts",
            cache_key="cache-key",
            payload={"tts_segments": [{"path": str(audio_path), "text": "hello"}]},
            artifact_paths=[str(audio_path)],
            file_manager=file_manager,
        )
        audio_path.unlink()

        payload = cache_manager.load_operation_bundle("tts", "cache-key", file_manager)

        self.assertIsNotNone(payload)
        self.assertEqual(audio_path.read_text(encoding="utf-8"), "audio-bytes")
        self.assertEqual(payload["tts_segments"][0]["path"], str(audio_path))
