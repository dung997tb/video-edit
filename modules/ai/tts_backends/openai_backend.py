from __future__ import annotations

from pathlib import Path

from modules.ai.tts_backends.base import TTSBackend


class OpenAITTSBackend(TTSBackend):
    def __init__(self, *, api_key: str | None, model: str = "gpt-4o-mini-tts") -> None:
        self.api_key = api_key
        self.model = model

    def generate(self, text: str, output_path: Path, *, voice: str, rate: str, volume: str) -> None:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for TTS_ENGINE=openai")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai is required for TTS_ENGINE=openai") from exc

        client = OpenAI(api_key=self.api_key)
        with client.audio.speech.with_streaming_response.create(
            model=self.model,
            voice=voice,
            input=text,
            response_format="mp3",
        ) as response:
            response.stream_to_file(output_path)
