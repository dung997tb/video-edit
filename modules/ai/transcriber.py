from __future__ import annotations

import json

from core.cache import make_operation_cache_key
from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register


@register
class TranscriberModule(BaseModule):
    NAME = "transcript"

    def cache_inputs(self, context) -> dict:
        return {
            "model": self.params.get("model"),
            "language": self.params.get("language", "auto"),
            "device": self.params.get("device"),
            "compute_type": self.params.get("compute_type"),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {"audio_path": context.audio_path or ""}

    def execute(self, context, services) -> StepResult:
        if not context.audio_path:
            raise ValueError("audio_path is required before transcription")
        model_name = self.params.get("model", services.settings.whisper_model)
        language = self.params.get("language", "auto")
        operation_params = {
            "device": self.params.get("device", services.settings.whisper_device),
            "compute_type": self.params.get("compute_type", services.settings.whisper_compute_type),
        }
        cache_key = make_operation_cache_key(
            source_sha256=context.source_sha256,
            operation="transcript",
            model=model_name,
            language=language,
            params=operation_params,
            cache_version=services.settings.cache_version,
        )
        payload = None
        if not bool(context.state.get("cache_bust") or context.state.get("bypass_cache")):
            payload = services.cache_manager.load_operation_result("transcript", cache_key)
        if payload is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError("faster-whisper is required for transcription") from exc

            model = WhisperModel(
                model_name,
                device=operation_params["device"],
                compute_type=operation_params["compute_type"],
            )
            segments, info = model.transcribe(
                context.audio_path,
                language=None if language == "auto" else language,
            )
            payload = {
                "language": getattr(info, "language", language),
                "segments": [
                    {
                        "id": index,
                        "start": segment.start,
                        "end": segment.end,
                        "text": segment.text.strip(),
                    }
                    for index, segment in enumerate(segments, start=1)
                ],
            }
            services.cache_manager.save_operation_result("transcript", cache_key, payload)

        output_path = context.file_manager.step_file("transcript")
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        metadata = dict(context.metadata)
        metadata["detected_language"] = payload.get("language")
        return StepResult(
            context_patch={
                "transcript_path": str(output_path),
                "segments": payload["segments"],
                "metadata": metadata,
            },
            artifacts={"transcript": str(output_path)},
        )
