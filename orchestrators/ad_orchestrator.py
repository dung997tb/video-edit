from __future__ import annotations

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register
from orchestrators.base import PipelineOrchestrator


@register
class InjectAdTextModule(BaseModule):
    NAME = "inject_text"

    def upstream_artifact_hashes(self, context) -> dict:
        return {}

    def execute(self, context, services) -> StepResult:
        text = context.state.get("ad_text", "Chào mừng bạn đến với Mewo Camm.")
        segment = {"id": 1, "start": 0.0, "end": 5.0, "text": text}
        return StepResult(
            context_patch={
                "segments": [segment],
                "translated_segments": [segment],
            },
            artifacts={}
        )


class AdOrchestrator(PipelineOrchestrator):
    NAME = "ad_video"

    def build(self, job, services):
        from modules.ai.tts import TTSModule
        from modules.ai.voice_sync import VoiceSyncModule
        from modules.video.remux_audio import RemuxAudioModule
        from modules.ai.subtitle_gen import SubtitleModule
        from modules.video.subtitle_burn import SubtitleBurnModule

        return [
            InjectAdTextModule(),
            TTSModule(),
            VoiceSyncModule(),
            SubtitleModule(),
            SubtitleBurnModule(),
            RemuxAudioModule(),
        ]
