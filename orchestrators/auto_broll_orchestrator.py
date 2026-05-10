from __future__ import annotations

from orchestrators.base import PipelineOrchestrator


class AutoBrollOrchestrator(PipelineOrchestrator):
    NAME = "auto_broll"

    def build(self, job, services):
        from modules.ai.broll_injector import BrollInjectorModule
        from modules.ai.transcriber import TranscriberModule
        from modules.video.extract_audio import ExtractAudioModule

        payload = job.payload or {}
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
            BrollInjectorModule(params=payload),
        ]
