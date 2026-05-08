from __future__ import annotations

from orchestrators.base import PipelineOrchestrator


class SubtitleOrchestrator(PipelineOrchestrator):
    NAME = "subtitle"

    def build(self, job, services):
        from modules.ai.segmenter import SegmenterModule
        from modules.ai.subtitle_export import SubtitleExportModule
        from modules.ai.subtitle_gen import SubtitleModule
        from modules.ai.transcriber import TranscriberModule
        from modules.ai.translator import TranslatorModule
        from modules.video.extract_audio import ExtractAudioModule
        from modules.video.subtitle_burn import SubtitleBurnModule

        payload = job.payload or {}
        pipeline = [
            ExtractAudioModule(params=payload.get("extract_audio", {})),
            TranscriberModule(
                params={
                    "model": payload.get("whisper_model", services.settings.whisper_model),
                    "language": payload.get("source_language", "auto"),
                    "device": payload.get("whisper_device", services.settings.whisper_device),
                    "compute_type": payload.get("whisper_compute_type", services.settings.whisper_compute_type),
                }
            ),
            TranslatorModule(
                params={
                    "service": payload.get("translator_service", services.settings.translator_service),
                    "source_language": payload.get("source_language", "auto"),
                    "target_language": payload.get("target_language", "vi"),
                }
            ),
        ]
        if bool(payload.get("segmenter_enabled", True)):
            pipeline.append(
                SegmenterModule(
                    params={
                        "strategy": payload.get("segment_strategy", "slot_adaptive"),
                        "max_chars": payload.get("segment_max_chars", 80),
                        "chars_per_second": payload.get("segment_chars_per_second", 14.0),
                    }
                )
            )
        pipeline.append(SubtitleModule())
        if payload.get("burn_subtitle") or payload.get("burn_subtitles") or payload.get("hard_subtitles"):
            pipeline.append(SubtitleBurnModule())
        pipeline.append(SubtitleExportModule())
        return pipeline
