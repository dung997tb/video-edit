from __future__ import annotations

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register


DEFAULT_TTS_VOICE_BY_LANGUAGE = {
    "vi": "vi-VN-HoaiMyNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
}


@register
class MultilangFanOutModule(BaseModule):
    NAME = "multilang_fanout"

    def cache_inputs(self, context) -> dict:
        return {"target_languages": list(context.state.get("target_languages", []))}

    def execute(self, context, services) -> StepResult:
        target_languages = context.state.get("target_languages", [])
        if not isinstance(target_languages, list) or not target_languages:
            raise ValueError("multilang-dubbing requires payload.target_languages as a non-empty list")
        child_jobs = []
        source_key = context.state.get("source_key")
        for language in target_languages:
            child_payload = dict(context.state)
            child_payload.pop("target_languages", None)
            child_payload["target_language"] = language
            child_payload["parent_job_id"] = context.job_id
            if child_payload.get("output_name"):
                child_payload["output_name"] = f"{child_payload['output_name']}_{language}"
            if not child_payload.get("tts_voice"):
                default_voice = DEFAULT_TTS_VOICE_BY_LANGUAGE.get(str(language).lower())
                if default_voice:
                    child_payload["tts_voice"] = default_voice
            child_metadata = dict(context.metadata)
            child_metadata["parent_job_id"] = context.job_id
            kwargs = {}
            if source_key:
                child_payload["source_key"] = source_key
            elif str(context.input_video).startswith(("http://", "https://")):
                kwargs["input_uri"] = context.input_video
            else:
                kwargs["input_path"] = context.input_video
            child = services.job_manager.create_job(
                pipeline_type="dubbing",
                source_sha256=context.source_sha256,
                payload=child_payload,
                metadata=child_metadata,
                **kwargs,
            )
            child_jobs.append(child)
        return StepResult(
            context_patch={
                "output_video": "",
                "metadata": {
                    **context.metadata,
                    "output_kind": "fanout",
                    "child_job_ids": [job.id for job in child_jobs],
                    "target_languages": target_languages,
                },
            },
            artifacts={},
        )
