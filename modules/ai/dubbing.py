from __future__ import annotations

from modules.ai.audio_mixer import AudioMixerModule
from modules.ai.segmenter import SegmenterModule
from modules.ai.subtitle_gen import SubtitleModule
from modules.ai.transcriber import TranscriberModule
from modules.ai.translator import TranslatorModule
from modules.ai.tts import TTSModule
from modules.ai.voice_sync import VoiceSyncModule
from modules.video.extract_audio import ExtractAudioModule
from modules.video.remux_audio import RemuxAudioModule
from modules.video.subtitle_burn import SubtitleBurnModule


def build_dubbing_pipeline(job, services):
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
    if payload.get("segmenter_enabled") or payload.get("segment_max_chars"):
        pipeline.append(
            SegmenterModule(
                params={
                    "max_chars": payload.get("segment_max_chars", 80),
                }
            )
        )
    pipeline.extend(
        [
        SubtitleModule(),
        TTSModule(
            params={
                "voice": payload.get("tts_voice", services.settings.tts_default_voice),
                "rate": payload.get("tts_rate", services.settings.tts_rate),
                "volume": payload.get("tts_volume", services.settings.tts_volume),
            }
        ),
        VoiceSyncModule(
            params={
                "max_audio_stretch": payload.get("max_audio_stretch", services.settings.max_audio_stretch),
            }
        ),
        AudioMixerModule(params={"background_weight": payload.get("background_weight", 0.15)}),
        ]
    )
    if payload.get("burn_subtitles") or payload.get("hard_subtitles"):
        pipeline.append(SubtitleBurnModule())
    pipeline.append(RemuxAudioModule())
    return pipeline
