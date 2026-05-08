from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from core.cache import canonical_json, make_operation_cache_key, sha256_text, stable_value_signature
from core.models import StepResult
from core.process import run_subprocess
from modules.base import BaseModule
from modules.ai.tts_backends import build_tts_backend
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
        cached_payload = None
        if not bool(context.state.get("cache_bust") or context.state.get("bypass_cache")):
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
        backend = build_tts_backend(services.settings)
        tts_segments = self._generate_all_segments(
            source_segments,
            backend=backend,
            voice=voice,
            rate=rate,
            volume=volume,
            context=context,
            services=services,
        )
        artifacts = [segment["path"] for segment in tts_segments]
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

    def _generate_all_segments(self, segments, *, backend, voice, rate, volume, context, services) -> list[dict]:
        worker_count = min(
            max(1, int(context.state.get("tts_parallel_workers", getattr(services.settings, "tts_parallel_workers", 1)))),
            len(segments),
        )
        if worker_count == 1:
            return [
                self._generate_segment(segment, index, backend=backend, voice=voice, rate=rate, volume=volume, context=context, services=services)
                for index, segment in enumerate(segments, start=1)
            ]
        results: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {
                pool.submit(
                    self._generate_segment,
                    segment,
                    index,
                    backend=backend,
                    voice=voice,
                    rate=rate,
                    volume=volume,
                    context=context,
                    services=services,
                ): index
                for index, segment in enumerate(segments, start=1)
            }
            for future in as_completed(futures):
                index = futures[future]
                results[index] = future.result()
        return [results[index] for index in sorted(results)]

    def _generate_segment(self, segment, index: int, *, backend, voice: str, rate: str, volume: str, context, services) -> dict:
        wav_output = context.file_manager.step_file("tts", n=index)
        if services.job_manager.is_cancel_requested(context.job_id):
            from core.exceptions import JobCancelledError

            raise JobCancelledError(f"job {context.job_id} cancelled before TTS segment {index}")
        if segment["text"].strip():
            mp3_output = context.file_manager.temp(f"tts_tmp_{index:03d}.mp3")
            self._generate_mp3(segment["text"], mp3_output, backend=backend, voice=voice, rate=rate, volume=volume)
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
        return {
            "index": index,
            "start": segment["start"],
            "end": segment["end"],
            "text": segment["text"],
            "path": str(wav_output),
        }

    def _generate_mp3(self, text: str, output_path: Path, *, backend, voice: str, rate: str, volume: str) -> None:
        backend.generate(text, output_path, voice=voice, rate=rate, volume=volume)
