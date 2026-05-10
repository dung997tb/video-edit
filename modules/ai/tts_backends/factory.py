from __future__ import annotations

from modules.ai.tts_backends.base import TTSBackend
from modules.ai.tts_backends.edge_tts_backend import EdgeTTSBackend
from modules.ai.tts_backends.elevenlabs_backend import ElevenLabsTTSBackend
from modules.ai.tts_backends.google_cloud_backend import GoogleCloudTTSBackend
from modules.ai.tts_backends.openai_backend import OpenAITTSBackend


def build_tts_backend(settings, provider_config: dict | None = None) -> TTSBackend:
    provider_config = provider_config or {}
    engine = str(
        provider_config.get("provider")
        or provider_config.get("engine")
        or provider_config.get("service")
        or getattr(settings, "tts_engine", "edge-tts")
    ).strip().lower()
    if engine in {"edge", "edge-tts"}:
        return EdgeTTSBackend()
    if engine == "openai":
        return OpenAITTSBackend(
            api_key=provider_config.get("api_key") or getattr(settings, "openai_api_key", None),
            model=provider_config.get("model") or getattr(settings, "openai_tts_model", "gpt-4o-mini-tts"),
        )
    if engine in {"google", "google-cloud", "google_cloud"}:
        return GoogleCloudTTSBackend(api_key=provider_config.get("api_key") or getattr(settings, "google_cloud_tts_key", None))
    if engine in {"elevenlabs", "eleven_labs", "eleven-labs"}:
        return ElevenLabsTTSBackend(
            api_key=provider_config.get("api_key") or getattr(settings, "elevenlabs_api_key", None),
            model=provider_config.get("model") or getattr(settings, "elevenlabs_tts_model", "eleven_multilingual_v2"),
            base_url=provider_config.get("base_url") or "https://api.elevenlabs.io/v1",
            timeout_seconds=float(provider_config.get("timeout_seconds", 60.0)),
        )
    raise RuntimeError(f"unsupported TTS_ENGINE: {engine}")
