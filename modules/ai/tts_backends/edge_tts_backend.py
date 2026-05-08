from __future__ import annotations

import asyncio
from pathlib import Path

from modules.ai.tts_backends.base import TTSBackend


class EdgeTTSBackend(TTSBackend):
    def generate(self, text: str, output_path: Path, *, voice: str, rate: str, volume: str) -> None:
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError("edge-tts is required for TTS_ENGINE=edge-tts") from exc

        async def _run() -> None:
            communicator = edge_tts.Communicate(text, voice=voice, rate=rate, volume=volume)
            await communicator.save(str(output_path))

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_run())
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            asyncio.set_event_loop(None)
            loop.close()
