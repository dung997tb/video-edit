from __future__ import annotations

from orchestrators.base import PipelineOrchestrator


class AudioExtractOrchestrator(PipelineOrchestrator):
    NAME = "audio-extract"

    def build(self, job, services):
        from modules.audio.audio_export import AudioExportModule
        from modules.audio.audio_normalize import AudioNormalizeModule
        from modules.video.extract_audio import ExtractAudioModule

        payload = job.payload or {}
        pipeline = [
            ExtractAudioModule(
                params={
                    "sample_rate": payload.get("sample_rate", 24000),
                    "channels": payload.get("channels", 1),
                }
            )
        ]
        if bool(payload.get("normalize", True)):
            pipeline.append(AudioNormalizeModule(params=payload.get("normalize_params", {})))
        pipeline.append(AudioExportModule())
        return pipeline
