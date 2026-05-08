from __future__ import annotations

from modules.ai.tts_backends.base import TTSBackend
from modules.ai.tts_backends.edge_tts_backend import EdgeTTSBackend
from modules.ai.tts_backends.google_cloud_backend import GoogleCloudTTSBackend
from modules.ai.tts_backends.openai_backend import OpenAITTSBackend


def build_tts_backend(settings) -> TTSBackend:
    engine = str(getattr(settings, "tts_engine", "edge-tts")).strip().lower()
    if engine in {"edge", "edge-tts"}:
        return EdgeTTSBackend()
    if engine == "openai":
        return OpenAITTSBackend(
            api_key=getattr(settings, "openai_api_key", None),
            model=getattr(settings, "openai_tts_model", "gpt-4o-mini-tts"),
        )
    if engine in {"google", "google-cloud", "google_cloud"}:
        return GoogleCloudTTSBackend(api_key=getattr(settings, "google_cloud_tts_key", None))
    raise RuntimeError(f"unsupported TTS_ENGINE: {engine}")
