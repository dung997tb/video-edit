from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SECRET_KEY_NAMES = {
    "api_key",
    "apikey",
    "access_key",
    "secret_key",
    "token",
    "access_token",
    "refresh_token",
    "bearer_token",
    "authorization",
    "auth_token",
    "password",
    "client_secret",
}


def redact_hint(value: Any) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    if len(raw) <= 4:
        return "***"
    return f"***{raw[-4:]}"


def is_secret_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return normalized in SECRET_KEY_NAMES or normalized.endswith("_api_key") or normalized.endswith("_token")


def split_redacted_secrets(payload: Any) -> tuple[Any, dict[str, str]]:
    secrets: dict[str, str] = {}
    redacted = _redact(payload, path=(), secrets=secrets)
    return redacted, secrets


def redact_secrets(payload: Any) -> Any:
    return split_redacted_secrets(payload)[0]


def _redact(value: Any, *, path: tuple[str, ...], secrets: dict[str, str]) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            child_path = (*path, key_text)
            if is_secret_key(key_text) and item not in (None, ""):
                secrets[".".join(child_path)] = str(item)
                result[key_text] = redact_hint(item)
                result.setdefault(f"{key_text}_source", "request")
                result.setdefault(f"{key_text}_hint", redact_hint(item))
                continue
            result[key_text] = _redact(item, path=child_path, secrets=secrets)
        return result
    if isinstance(value, list):
        return [_redact(item, path=(*path, str(index)), secrets=secrets) for index, item in enumerate(value)]
    if isinstance(value, tuple):
        return [_redact(item, path=(*path, str(index)), secrets=secrets) for index, item in enumerate(value)]
    return value
