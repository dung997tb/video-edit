from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from modules.ai.tts_backends.base import TTSBackend


class EdgeTTSBackend(TTSBackend):
    def __init__(self, settings: Any = None, provider_config: dict[str, Any] | None = None) -> None:
        self.settings = settings
        self.provider_config = provider_config or {}

    def generate(self, text: str, output_path: Path, *, voice: str, rate: str, volume: str) -> None:
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError("edge-tts is required for TTS_ENGINE=edge-tts") from exc

        async def _run() -> None:
            attempts = 3
            backoff = 1.0
            last_err = None
            for attempt in range(attempts):
                try:
                    communicator = edge_tts.Communicate(text, voice=voice, rate=rate, volume=volume)
                    await communicator.save(str(output_path))
                    return
                except Exception as e:
                    last_err = e
                    if attempt < attempts - 1:
                        await asyncio.sleep(backoff)
                        backoff *= 2.0
            raise last_err or RuntimeError("Edge TTS failed after retries")

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_run())
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception as exc:
            fallback_success = self._generate_fallback(text, output_path, voice=voice, rate=rate, volume=volume)
            if not fallback_success:
                raise exc
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    def _generate_fallback(self, text: str, output_path: Path, *, voice: str, rate: str, volume: str) -> bool:
        # 1. Try OpenAI fallback
        openai_key = self.provider_config.get("api_key")
        if not openai_key and self.settings:
            openai_key = getattr(self.settings, "openai_api_key", None)
            
        if openai_key:
            try:
                from modules.ai.tts_backends.openai_backend import OpenAITTSBackend
                openai_model = "gpt-4o-mini-tts"
                if self.settings:
                    openai_model = getattr(self.settings, "openai_tts_model", "gpt-4o-mini-tts")
                backend = OpenAITTSBackend(api_key=openai_key, model=openai_model)
                backend.generate(text, output_path, voice=voice, rate=rate, volume=volume)
                return True
            except Exception:
                pass
        
        # 2. Try Google Translate TTS fallback
        try:
            import urllib.request
            import urllib.parse
            q = urllib.parse.quote(text)
            lang = "-".join(voice.split("-")[:2]) if "-" in voice else "vi"
            lang = lang.split("-")[0]
            url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={q}&tl={lang}&client=tw-ob"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                output_path.write_bytes(response.read())
            return True
        except Exception:
            pass
            
        return False
