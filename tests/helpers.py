from __future__ import annotations

import os
import uuid
from pathlib import Path
from types import SimpleNamespace

from core.artifact_store import LocalArtifactStore
from core.asset_graph import InMemoryAssetGraph
from core.cache import CacheManager
from core.events import InMemoryEventBus
from core.job_manager import InMemoryJobRepository, JobManager
from core.process import ProcessRegistry


def _resolve_binary(default_name: str, env_var: str) -> str:
    candidate = os.getenv(env_var)
    if candidate and Path(candidate).exists():
        return candidate
    try:
        from config import settings as app_settings
    except Exception:
        return default_name
    configured = getattr(app_settings, env_var.lower(), None)
    if configured and Path(str(configured)).exists():
        return str(configured)
    return default_name


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
        max_job_attempts=3,
        max_job_duration_seconds=3600,
        heartbeat_interval_seconds=0.01,
        cancel_grace_seconds=0.1,
        step_retry_attempts=2,
        step_retry_delay_seconds=0.0,
        worker_poll_interval_seconds=0.01,
        worker_poll_min_seconds=0.01,
        worker_poll_max_seconds=0.05,
        worker_poll_backoff_factor=1.5,
        whisper_model="base",
        whisper_device="cpu",
        whisper_compute_type="int8",
        translator_service="google",
        tts_engine="edge-tts",
        tts_parallel_workers=1,
        tts_default_voice="vi-VN-HoaiMyNeural",
        tts_rate="+0%",
        tts_volume="+0%",
        openai_api_key=None,
        openai_tts_model="gpt-4o-mini-tts",
        google_cloud_tts_key=None,
        ffmpeg_path=_resolve_binary("ffmpeg", "FFMPEG_PATH"),
        ffprobe_path=_resolve_binary("ffprobe", "FFPROBE_PATH"),
        max_audio_stretch=1.3,
        job_backend="memory",
        artifact_store_backend="local",
        secret_store_backend="memory",
        api_embedded_worker=True,
        api_allow_input_path=False,
        api_allow_client_source_sha256=False,
        api_allowed_input_uri_schemes="http,https",
        api_allow_private_network_urls=False,
        api_rate_limit_per_minute=0,
        webhooks_enabled=False,
        webhook_timeout_seconds=0.1,
        webhook_max_retries=3,
        metrics_enabled=True,
        tracing_enabled=False,
    )
    artifact_store = LocalArtifactStore(root / "shared-artifacts")
    return SimpleNamespace(
        settings=settings,
        artifact_store=artifact_store,
        cache_manager=CacheManager(artifact_store=artifact_store, cache_version=settings.cache_version),
        job_manager=JobManager(InMemoryJobRepository()),
        process_registry=ProcessRegistry(),
        asset_graph=InMemoryAssetGraph(),
        event_bus=InMemoryEventBus(),
        pipeline_builders={},
    )


def make_test_root(name: str) -> Path:
    root = Path("test_runs") / f"{name}-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root
