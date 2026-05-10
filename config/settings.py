from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any, get_args, get_origin

try:
    from pydantic import Field
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover - fallback for minimal local environments
    class _FieldInfo:
        def __init__(self, default: Any = None, alias: str | None = None) -> None:
            self.default = default
            self.alias = alias

    def Field(default: Any = None, alias: str | None = None) -> _FieldInfo:
        return _FieldInfo(default=default, alias=alias)

    class SettingsConfigDict(dict):
        pass

    class BaseSettings:
        model_config: SettingsConfigDict = SettingsConfigDict()

        def __init__(self, **values: Any) -> None:
            annotations = getattr(self.__class__, "__annotations__", {})
            for name in annotations:
                declared = getattr(self.__class__, name, None)
                alias = None
                default = declared
                if isinstance(declared, _FieldInfo):
                    alias = declared.alias
                    default = declared.default
                if name in values:
                    value = values[name]
                elif alias and alias in values:
                    value = values[alias]
                elif alias and alias in os.environ:
                    value = os.environ[alias]
                else:
                    value = default
                setattr(self, name, self._coerce(annotations[name], value))

        def _coerce(self, annotation: Any, value: Any) -> Any:
            if value is None:
                return None
            origin = get_origin(annotation)
            if origin is not None:
                args = [arg for arg in get_args(annotation) if arg is not type(None)]
                if args:
                    return self._coerce(args[0], value)
            if annotation is Path:
                return value if isinstance(value, Path) else Path(value)
            if annotation is int:
                return int(value)
            if annotation is float:
                return float(value)
            if annotation is bool:
                if isinstance(value, bool):
                    return value
                return str(value).strip().lower() in {"1", "true", "yes", "on"}
            return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="ai-video-engine", alias="APP_NAME")

    ffmpeg_path: str = Field(default="ffmpeg", alias="FFMPEG_PATH")
    ffprobe_path: str = Field(default="ffprobe", alias="FFPROBE_PATH")

    whisper_model: str = Field(default="base", alias="WHISPER_MODEL")
    whisper_device: str = Field(default="cpu", alias="WHISPER_DEVICE")
    whisper_compute_type: str = Field(default="int8", alias="WHISPER_COMPUTE_TYPE")

    translator_service: str = Field(default="google", alias="TRANSLATOR_SERVICE")
    deepl_api_key: str | None = Field(default=None, alias="DEEPL_API_KEY")
    libretranslate_url: str | None = Field(default=None, alias="LIBRETRANSLATE_URL")

    tts_engine: str = Field(default="edge-tts", alias="TTS_ENGINE")
    tts_parallel_workers: int = Field(default=1, alias="TTS_PARALLEL_WORKERS")
    tts_default_voice: str = Field(default="vi-VN-HoaiMyNeural", alias="TTS_DEFAULT_VOICE")
    tts_rate: str = Field(default="+0%", alias="TTS_RATE")
    tts_volume: str = Field(default="+0%", alias="TTS_VOLUME")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_tts_model: str = Field(default="gpt-4o-mini-tts", alias="OPENAI_TTS_MODEL")
    google_cloud_tts_key: str | None = Field(default=None, alias="GOOGLE_CLOUD_TTS_KEY")
    elevenlabs_api_key: str | None = Field(default=None, alias="ELEVENLABS_API_KEY")
    elevenlabs_tts_model: str = Field(default="eleven_multilingual_v2", alias="ELEVENLABS_TTS_MODEL")

    supabase_url: str | None = Field(default=None, alias="SUPABASE_URL")
    supabase_key: str | None = Field(default=None, alias="SUPABASE_KEY")
    supabase_jobs_table: str = Field(default="jobs", alias="SUPABASE_JOBS_TABLE")
    supabase_storage_bucket: str = Field(default="artifacts", alias="SUPABASE_STORAGE_BUCKET")

    job_backend: str = Field(default="memory", alias="JOB_BACKEND")
    artifact_store_backend: str = Field(default="local", alias="ARTIFACT_STORE_BACKEND")
    asset_graph_backend: str = Field(default="memory", alias="ASSET_GRAPH_BACKEND")
    event_log_backend: str = Field(default="memory", alias="EVENT_LOG_BACKEND")

    output_dir: Path = Field(default=Path("output"), alias="OUTPUT_DIR")
    temp_dir: Path = Field(default=Path("temp"), alias="TEMP_DIR")
    logs_dir: Path = Field(default=Path("logs"), alias="LOGS_DIR")
    cache_dir: Path = Field(default=Path("cache"), alias="CACHE_DIR")

    max_workers: int = Field(default=2, alias="MAX_WORKERS")
    worker_poll_interval_seconds: float = Field(default=1.0, alias="WORKER_POLL_INTERVAL_SECONDS")
    worker_poll_min_seconds: float = Field(default=0.2, alias="WORKER_POLL_MIN_SECONDS")
    worker_poll_max_seconds: float = Field(default=1.0, alias="WORKER_POLL_MAX_SECONDS")
    worker_poll_backoff_factor: float = Field(default=1.5, alias="WORKER_POLL_BACKOFF_FACTOR")
    job_lease_seconds: int = Field(default=30, alias="JOB_LEASE_SECONDS")
    heartbeat_interval_seconds: float = Field(default=10.0, alias="HEARTBEAT_INTERVAL_SECONDS")
    cancel_grace_seconds: float = Field(default=5.0, alias="CANCEL_GRACE_SECONDS")
    step_retry_attempts: int = Field(default=2, alias="STEP_RETRY_ATTEMPTS")
    step_retry_delay_seconds: float = Field(default=1.0, alias="STEP_RETRY_DELAY_SECONDS")
    max_audio_stretch: float = Field(default=1.3, alias="MAX_AUDIO_STRETCH")
    cache_version: str = Field(default="v1", alias="CACHE_VERSION")

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=6666, alias="API_PORT")
    api_secret_key: str = Field(default="change-me-in-production", alias="API_SECRET_KEY")
    api_auth_enabled: bool = Field(default=True, alias="API_AUTH_ENABLED")
    api_embedded_worker: bool = Field(default=True, alias="API_EMBEDDED_WORKER")
    api_allow_input_path: bool = Field(default=False, alias="API_ALLOW_INPUT_PATH")
    api_allow_client_source_sha256: bool = Field(default=False, alias="API_ALLOW_CLIENT_SOURCE_SHA256")
    api_allowed_input_uri_schemes: str = Field(default="http,https", alias="API_ALLOWED_INPUT_URI_SCHEMES")
    api_upload_max_bytes: int = Field(default=536_870_912, alias="API_UPLOAD_MAX_BYTES")
    api_rate_limit_per_minute: int = Field(default=60, alias="API_RATE_LIMIT_PER_MINUTE")

    webhooks_enabled: bool = Field(default=False, alias="WEBHOOKS_ENABLED")
    webhook_timeout_seconds: float = Field(default=10.0, alias="WEBHOOK_TIMEOUT_SECONDS")

    metrics_enabled: bool = Field(default=True, alias="METRICS_ENABLED")
    tracing_enabled: bool = Field(default=False, alias="TRACING_ENABLED")

    worker_id: str | None = Field(default=None, alias="WORKER_ID")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def resolved_worker_id(self) -> str:
        if self.worker_id:
            return self.worker_id
        hostname = socket.gethostname().replace(" ", "-")
        return f"{hostname}-{os.getpid()}"

    def to_dict(self) -> dict[str, Any]:
        fields = getattr(self.__class__, "__annotations__", {})
        return {name: getattr(self, name) for name in fields}

    def with_overrides(self, **values: Any) -> "Settings":
        payload = self.to_dict()
        payload.update(values)
        return self.__class__(**payload)
