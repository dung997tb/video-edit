from __future__ import annotations

import re


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def normalize_artifact_key(key: str) -> str:
    """Return a safe artifact-store key or raise ValueError."""
    if not isinstance(key, str):
        raise ValueError("artifact key must be a string")
    normalized = key.strip()
    if not normalized:
        raise ValueError("artifact key must not be empty")
    if normalized != key:
        raise ValueError("artifact key must not have leading or trailing whitespace")
    if "\\" in normalized:
        raise ValueError("artifact key must use forward slashes")
    if ":" in normalized:
        raise ValueError("artifact key must not contain ':'")
    if normalized.startswith("/"):
        raise ValueError("artifact key must be relative")
    if _CONTROL_CHARS_RE.search(normalized):
        raise ValueError("artifact key must not contain control characters")

    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("artifact key must not contain empty, '.', or '..' segments")
    return "/".join(parts)
