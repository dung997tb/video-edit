from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

from modules.ai.tts_backends.base import TTSBackend


class ElevenLabsTTSBackend(TTSBackend):
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "eleven_multilingual_v2",
        base_url: str = "https://api.elevenlabs.io/v1",
        timeout_seconds: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def generate(self, text: str, output_path: Path, *, voice: str, rate: str, volume: str) -> None:
        if not self.api_key:
            raise RuntimeError("ElevenLabs TTS requires an API key")
        voice_id = voice.strip()
        if not voice_id:
            raise RuntimeError("ElevenLabs TTS requires a voice id")
        payload = {
            "text": text,
            "model_id": self.model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }
        request = Request(
            f"{self.base_url}/text-to-speech/{voice_id}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
                "xi-api-key": self.api_key,
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            output_path.write_bytes(response.read())
