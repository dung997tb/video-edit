from __future__ import annotations

import asyncio
from pathlib import Path

from core.cache import canonical_json, make_operation_cache_key, sha256_text, stable_value_signature
from core.models import StepResult
from core.process import run_subprocess
from modules.base import BaseModule
from modules.registry import register


@register
class TTSModule(BaseModule):
    NAME = "tts"

    def cache_inputs(self, context) -> dict:
        return {
            "voice": self.params.get("voice"),
            "rate": self.params.get("rate"),
            "volume": self.params.get("volume"),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        source_segments = context.translated_segments or context.segments
        return {
            "segments": stable_value_signature({"segments": source_segments}),
        }

    def execute(self, context, services) -> StepResult:
        source_segments = context.translated_segments or context.segments
        if not source_segments:
            raise ValueError("segments are required before TTS")
        target_language = context.metadata.get("target_language", context.state.get("target_language", "vi"))
        voice = self.params.get("voice", context.state.get("tts_voice", services.settings.tts_default_voice))
        rate = self.params.get("rate", context.state.get("tts_rate", services.settings.tts_rate))
        volume = self.params.get("volume", context.state.get("tts_volume", services.settings.tts_volume))
        cache_key = make_operation_cache_key(
            source_sha256=context.source_sha256,
            operation="tts",
            model=services.settings.tts_engine,
            language=target_language,
            params={
                "voice": voice,
                "rate": rate,
                "volume": volume,
                "translator_service": context.state.get("translator_service", services.settings.translator_service),
                "translated_segments_sha256": sha256_text(
                    canonical_json({"segments": [{k: segment[k] for k in ("start", "end", "text")} for segment in source_segments]})
                ),
            },
            cache_version=services.settings.cache_version,
        )
        cached_payload = services.cache_manager.load_operation_bundle("tts", cache_key, context.file_manager)
        if cached_payload is not None:
            cached_segments = cached_payload.get("tts_segments", [])
            cached_metadata = dict(context.metadata)
            cached_metadata.update(cached_payload.get("metadata", {}))
            return StepResult(
                context_patch={
                    "tts_segments": cached_segments,
                    "metadata": cached_metadata,
                },
                artifacts={"tts_segments": [segment["path"] for segment in cached_segments]},
            )
        artifacts: list[str] = []
        tts_segments: list[dict] = []
        for index, segment in enumerate(source_segments, start=1):
            wav_output = context.file_manager.step_file("tts", n=index)
            if segment["text"].strip():
                mp3_output = context.file_manager.temp(f"tts_tmp_{index:03d}.mp3")
                self._generate_mp3(segment["text"], mp3_output, voice=voice, rate=rate, volume=volume)
                run_subprocess(
                    [
                        services.settings.ffmpeg_path,
                        "-y",
                        "-i",
                        str(mp3_output),
                        "-ar",
                        "24000",
                        "-ac",
                        "1",
                        str(wav_output),
                    ],
                    job_id=context.job_id,
                    job_manager=services.job_manager,
                    process_registry=services.process_registry,
                    cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
                    grace_seconds=services.settings.cancel_grace_seconds,
                )
            else:
                run_subprocess(
                    [
                        services.settings.ffmpeg_path,
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        "anullsrc=r=24000:cl=mono",
                        "-t",
                        f"{max(segment['end'] - segment['start'], 0.1):.3f}",
                        str(wav_output),
                    ],
                    job_id=context.job_id,
                    job_manager=services.job_manager,
                    process_registry=services.process_registry,
                    cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
                    grace_seconds=services.settings.cancel_grace_seconds,
                )
            artifacts.append(str(wav_output))
            tts_segments.append(
                {
                    "index": index,
                    "start": segment["start"],
                    "end": segment["end"],
                    "text": segment["text"],
                    "path": str(wav_output),
                }
            )
        metadata = dict(context.metadata)
        metadata["tts_voice"] = voice
        services.cache_manager.save_operation_bundle(
            operation="tts",
            cache_key=cache_key,
            payload={"tts_segments": tts_segments, "metadata": {"tts_voice": voice}},
            artifact_paths=artifacts,
            file_manager=context.file_manager,
        )
        return StepResult(
            context_patch={"tts_segments": tts_segments, "metadata": metadata},
            artifacts={"tts_segments": artifacts},
        )

    def _generate_mp3(self, text: str, output_path: Path, *, voice: str, rate: str, volume: str) -> None:
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError("edge-tts is required for TTS") from exc

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
