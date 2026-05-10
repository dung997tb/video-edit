from __future__ import annotations

from orchestrators.base import PipelineOrchestrator


class SemanticEditOrchestrator(PipelineOrchestrator):
    NAME = "semantic_edit"

    def build(self, job, services):
        from modules.ai.silence_remover import SilenceRemoverModule
        from modules.ai.semantic_edit import SemanticEditModule
        from modules.ai.transcriber import TranscriberModule
        from modules.video.extract_audio import ExtractAudioModule

        payload = job.payload or {}
        if payload.get("command") == "silence_cut":
            return [SilenceRemoverModule(params=payload)]
        return [
            ExtractAudioModule(params=payload.get("extract_audio", {})),
            TranscriberModule(
                params={
                    "model": payload.get("whisper_model", services.settings.whisper_model),
                    "language": payload.get("source_language", "auto"),
                    "device": payload.get("whisper_device", services.settings.whisper_device),
                    "compute_type": payload.get("whisper_compute_type", services.settings.whisper_compute_type),
                }
            ),
            SemanticEditModule(params=payload),
        ]
