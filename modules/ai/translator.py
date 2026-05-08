from __future__ import annotations

import json

from core.cache import make_operation_cache_key, stable_value_signature
from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register


@register
class TranslatorModule(BaseModule):
    NAME = "translate"

    def cache_inputs(self, context) -> dict:
        return {
            "service": self.params.get("service"),
            "source_language": self.params.get("source_language", "auto"),
            "target_language": self.params.get("target_language", "vi"),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {
            "transcript_path": context.transcript_path or stable_value_signature({"segments": context.segments}),
        }

    def execute(self, context, services) -> StepResult:
        if not context.segments:
            raise ValueError("segments are required before translation")
        service = self.params.get("service", services.settings.translator_service)
        source_language = self.params.get("source_language", context.metadata.get("detected_language", "auto"))
        target_language = self.params.get("target_language", context.state.get("target_language", "vi"))
        transcript_signature = (
            stable_value_signature({"transcript_path": context.transcript_path})
            if context.transcript_path
            else stable_value_signature({"segments": context.segments})
        )
        cache_key = make_operation_cache_key(
            source_sha256=context.source_sha256,
            operation="translate",
            model=service,
            language=target_language,
            params={
                "source_language": source_language,
                "transcript_signature": transcript_signature,
            },
            cache_version=services.settings.cache_version,
        )
        payload = None
        if not bool(context.state.get("cache_bust") or context.state.get("bypass_cache")):
            payload = services.cache_manager.load_operation_result("translate", cache_key)
        if payload is None:
            translated_segments = []
            translator = self._build_translator(
                service=service,
                source_language=source_language,
                target_language=target_language,
                services=services,
            )
            for segment in context.segments:
                text = segment["text"].strip()
                translated = text if not text or source_language == target_language else translator(text)
                translated_segments.append({**segment, "text": translated})
            payload = {
                "service": service,
                "source_language": source_language,
                "target_language": target_language,
                "segments": translated_segments,
            }
            services.cache_manager.save_operation_result("translate", cache_key, payload)

        output_path = context.file_manager.step_file("translate")
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        metadata = dict(context.metadata)
        metadata["target_language"] = target_language
        return StepResult(
            context_patch={
                "translation_path": str(output_path),
                "translated_segments": payload["segments"],
                "metadata": metadata,
            },
            artifacts={"translation": str(output_path)},
        )

    def _build_translator(self, *, service: str, source_language: str, target_language: str, services):
        if service == "deepl":
            try:
                from deep_translator import DeeplTranslator
            except ImportError as exc:
                raise RuntimeError("deep-translator is required for Deepl translation") from exc
            if not services.settings.deepl_api_key:
                raise RuntimeError("DEEPL_API_KEY is required for Deepl translation")
            translator = DeeplTranslator(
                api_key=services.settings.deepl_api_key,
                source=source_language,
                target=target_language,
            )
            return translator.translate

        try:
            from deep_translator import GoogleTranslator, LibreTranslator
        except ImportError as exc:
            raise RuntimeError("deep-translator is required for translation") from exc

        if service == "libre":
            translator = LibreTranslator(
                source=source_language,
                target=target_language,
                base_url=services.settings.libretranslate_url,
            )
            return translator.translate

        translator = GoogleTranslator(source=source_language, target=target_language)
        return translator.translate
