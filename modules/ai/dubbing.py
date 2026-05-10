from __future__ import annotations

from modules.ai.audio_mixer import AudioMixerModule
from modules.ai.segmenter import SegmenterModule
from modules.ai.subtitle_gen import SubtitleModule
from modules.ai.transcriber import TranscriberModule
from modules.ai.translator import TranslatorModule
from modules.ai.tts import TTSModule
from modules.ai.voice_sync import VoiceSyncModule
from modules.ai.voice_sync_retry import VoiceSyncRetryModule
from modules.video.extract_audio import ExtractAudioModule
from modules.video.remux_audio import RemuxAudioModule
from modules.video.subtitle_burn import SubtitleBurnModule


def build_dubbing_pipeline(job, services):
    payload = job.payload or {}
    segmenter_enabled = bool(payload.get("segmenter_enabled", True))
    segment_strategy = payload.get("segment_strategy", "slot_adaptive")
    segment_max_chars = payload.get("segment_max_chars", 80)
    segment_chars_per_second = payload.get("segment_chars_per_second", 14.0)
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
    if segmenter_enabled:
        pipeline.append(
            SegmenterModule(
                params={
                    "strategy": segment_strategy,
                    "max_chars": segment_max_chars,
                    "chars_per_second": segment_chars_per_second,
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
            VoiceSyncRetryModule(
                params={
                    "retry_on_overflow": payload.get("segment_retry_on_overflow", True),
                    "tighten_factor": payload.get("segment_retry_tighten_factor", 0.85),
                    "segment_strategy": segment_strategy,
                    "segment_max_chars": segment_max_chars,
                    "segment_chars_per_second": segment_chars_per_second,
                    "resplit_on_unresolved": payload.get("segment_resplit_on_unresolved", True),
                    "max_resplit_parts": payload.get("segment_max_resplit_parts", 4),
                }
            ),
            AudioMixerModule(
                params={
                    "background_weight": payload.get("background_music_volume", payload.get("background_weight", 0.15)),
                    "original_volume": payload.get("original_volume", payload.get("source_volume")),
                    "translated_volume": payload.get("translated_volume", payload.get("tts_volume_linear", 1.0)),
                    "duck_during_speech": payload.get("duck_during_speech", False),
                    "duck_level_db": payload.get("duck_level_db", -12),
                }
            ),
        ]
    )
    if payload.get("burn_subtitles") or payload.get("hard_subtitles"):
        pipeline.append(SubtitleBurnModule())
    pipeline.append(RemuxAudioModule())
    return pipeline
