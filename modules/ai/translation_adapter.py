from __future__ import annotations

import json
from typing import Any, Callable
from urllib.request import Request, urlopen


def build_translation_callable(
    *,
    service: str,
    source_language: str,
    target_language: str,
    services: Any,
    provider_config: dict[str, Any] | None = None,
) -> Callable[[str], str]:
    provider_config = provider_config or {}
    provider = str(
        provider_config.get("provider")
        or provider_config.get("service")
        or provider_config.get("engine")
        or service
    ).strip().lower()
    if provider in {"generic_http", "http", "custom_http"}:
        return _generic_http_translator(
            provider_config=provider_config,
            source_language=source_language,
            target_language=target_language,
        )
    if provider == "deepl":
        try:
            from deep_translator import DeeplTranslator
        except ImportError as exc:
            raise RuntimeError("deep-translator is required for Deepl translation") from exc
        api_key = provider_config.get("api_key") or getattr(services.settings, "deepl_api_key", None)
        if not api_key:
            raise RuntimeError("DEEPL_API_KEY is required for Deepl translation")
        translator = DeeplTranslator(api_key=api_key, source=source_language, target=target_language)
        return translator.translate

    try:
        from deep_translator import GoogleTranslator, LibreTranslator
    except ImportError as exc:
        raise RuntimeError("deep-translator is required for translation") from exc

    if provider == "libre":
        translator = LibreTranslator(
            source=source_language,
            target=target_language,
            base_url=provider_config.get("base_url") or getattr(services.settings, "libretranslate_url", None),
        )
        return translator.translate

    translator = GoogleTranslator(source=source_language, target=target_language)
    return translator.translate


def _generic_http_translator(
    *,
    provider_config: dict[str, Any],
    source_language: str,
    target_language: str,
) -> Callable[[str], str]:
    api_url = provider_config.get("api_url") or provider_config.get("url")
    if not api_url:
        raise RuntimeError("generic HTTP translation requires api_url")
    api_key = provider_config.get("api_key")
    timeout = float(provider_config.get("timeout_seconds", 60.0))
    headers = {"Content-Type": "application/json"}
    headers.update(dict(provider_config.get("headers") or {}))
    if api_key and "Authorization" not in headers and "authorization" not in {key.lower() for key in headers}:
        scheme = provider_config.get("auth_scheme", "Bearer")
        headers["Authorization"] = f"{scheme} {api_key}".strip()

    def translate(text: str) -> str:
        payload = {
            "text": text,
            "source_language": source_language,
            "target_language": target_language,
            "request": provider_config.get("request"),
        }
        request = Request(
            str(api_url),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method=str(provider_config.get("method", "POST")).upper(),
        )
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        for key in ("translation", "translated_text", "text", "output"):
            if isinstance(data, dict) and key in data:
                return str(data[key])
        if isinstance(data, dict) and isinstance(data.get("choices"), list) and data["choices"]:
            message = data["choices"][0].get("message", {})
            if isinstance(message, dict) and "content" in message:
                return str(message["content"])
        raise RuntimeError("generic HTTP translation response must include translation/text/output")

    return translate
