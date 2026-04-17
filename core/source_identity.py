from __future__ import annotations

from core.artifact_store import ArtifactStore
from core.cache import hash_file, sha256_bytes, sha256_text


def resolve_source_sha256(
    *,
    source_sha256: str | None,
    input_path: str | None = None,
    input_uri: str | None = None,
    source_key: str | None = None,
    artifact_store: ArtifactStore | None = None,
) -> str:
    if source_sha256:
        return source_sha256
    if input_path:
        try:
            return hash_file(input_path)
        except OSError as exc:
            raise ValueError(f"input_path not found: {input_path}") from exc
    if source_key:
        if artifact_store is None:
            raise ValueError("artifact_store is required when source_key is provided without source_sha256")
        try:
            return sha256_bytes(artifact_store.download_bytes(source_key))
        except Exception as exc:
            raise ValueError(f"source_key not found: {source_key}") from exc
    if input_uri:
        return sha256_text(f"input_uri:{input_uri}")
    raise ValueError("source_sha256 is required unless input_path, source_key, or input_uri is provided")
