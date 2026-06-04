from __future__ import annotations

import re

from core.artifact_key import normalize_artifact_key
from core.artifact_store import ArtifactStore
from core.cache import hash_file, sha256_bytes, sha256_text


_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _normalize_sha256(value: str) -> str:
    candidate = value.strip().lower()
    if not _SHA256_HEX_RE.fullmatch(candidate):
        raise ValueError("source_sha256 must be a valid 64-char hex sha256")
    return candidate


def resolve_source_sha256(
    *,
    source_sha256: str | None,
    input_path: str | None = None,
    input_uri: str | None = None,
    source_key: str | None = None,
    artifact_store: ArtifactStore | None = None,
    allow_explicit_source_sha256: bool = False,
) -> str:
    if input_path:
        try:
            return hash_file(input_path)
        except OSError as exc:
            raise ValueError(f"input_path not found: {input_path}") from exc
    if source_key:
        source_key = normalize_artifact_key(source_key)
        if artifact_store is None:
            raise ValueError("artifact_store is required when source_key is provided without source_sha256")
        try:
            return sha256_bytes(artifact_store.download_bytes(source_key))
        except Exception as exc:
            raise ValueError(f"source_key not found: {source_key}") from exc
    if input_uri:
        return sha256_text(f"input_uri:{input_uri}")
    if source_sha256:
        if not allow_explicit_source_sha256:
            raise ValueError(
                "source_sha256 direct input is disabled; provide input_path, input_uri, or source_key"
            )
        return _normalize_sha256(source_sha256)
    raise ValueError("input_path, source_key, input_uri, or source_sha256 is required")
