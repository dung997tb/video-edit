from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

from core.artifact_store import LocalArtifactStore
from core.cache import CacheManager
from core.job_manager import InMemoryJobRepository, JobManager
from core.process import ProcessRegistry


def make_services(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    settings = SimpleNamespace(
        temp_dir=root / "temp",
        output_dir=root / "output",
        logs_dir=root / "logs",
        cache_dir=root / "cache",
        cache_version="test-v1",
        worker_id="worker-test",
        resolved_worker_id="worker-test",
        max_workers=2,
        job_lease_seconds=30,
        heartbeat_interval_seconds=0.01,
        cancel_grace_seconds=0.1,
        step_retry_attempts=2,
        step_retry_delay_seconds=0.0,
        worker_poll_interval_seconds=0.01,
        whisper_model="base",
        whisper_device="cpu",
        whisper_compute_type="int8",
        translator_service="google",
        tts_default_voice="vi-VN-HoaiMyNeural",
        tts_rate="+0%",
        tts_volume="+0%",
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        max_audio_stretch=1.3,
        api_embedded_worker=True,
    )
    artifact_store = LocalArtifactStore(root / "shared-artifacts")
    return SimpleNamespace(
        settings=settings,
        artifact_store=artifact_store,
        cache_manager=CacheManager(artifact_store=artifact_store, cache_version=settings.cache_version),
        job_manager=JobManager(InMemoryJobRepository()),
        process_registry=ProcessRegistry(),
        pipeline_builders={},
    )


def make_test_root(name: str) -> Path:
    root = Path("test_runs") / f"{name}-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root
