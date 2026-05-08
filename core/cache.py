from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from core.artifact_store import ArtifactStore
from core.file_manager import FileManager
from core.models import StepArtifact, StepManifest, StepResult


ARTIFACT_TOKEN = "__artifact_path__"
FILE_SIGNATURE_TOKEN = "__file_sha256__"


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def hash_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _looks_like_path(value: str) -> bool:
    if not value:
        return False
    if any(separator in value for separator in ("\\", "/")):
        return True
    if len(value) >= 2 and value[1] == ":":
        return True
    if value.startswith("."):
        return True
    return bool(Path(value).suffix)


def _existing_file_signature(path: str | Path) -> str | None:
    raw_path = str(path).strip()
    if not raw_path or not _looks_like_path(raw_path):
        return None
    try:
        candidate = Path(raw_path)
        if candidate.is_file():
            return hash_file(candidate)
    except (OSError, ValueError):
        return None
    return None


def normalize_signature_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): normalize_signature_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_signature_value(item) for item in value]
    if isinstance(value, tuple):
        return [normalize_signature_value(item) for item in value]
    if isinstance(value, Path):
        signature = _existing_file_signature(value)
        return {FILE_SIGNATURE_TOKEN: signature} if signature else str(value)
    if isinstance(value, str):
        signature = _existing_file_signature(value)
        return {FILE_SIGNATURE_TOKEN: signature} if signature else value
    return value


def stable_value_signature(value: Any) -> str:
    return sha256_text(canonical_json({"value": normalize_signature_value(value)}))


def make_operation_cache_key(
    source_sha256: str,
    operation: str,
    model: str,
    language: str,
    params: dict[str, Any],
    cache_version: str,
) -> str:
    raw = "|".join(
        (
            source_sha256,
            operation,
            model,
            language,
            canonical_json(normalize_signature_value(params)),
            cache_version,
        )
    )
    return sha256_text(raw)


def make_step_cache_key(
    job_id: str,
    step_name: str,
    params: dict[str, Any],
    upstream_artifact_hashes: dict[str, Any],
    cache_version: str,
) -> str:
    raw = "|".join(
        (
            job_id,
            step_name,
            canonical_json(normalize_signature_value(params)),
            canonical_json(normalize_signature_value(upstream_artifact_hashes)),
            cache_version,
        )
    )
    return sha256_text(raw)


class CacheManager:
    def __init__(self, artifact_store: ArtifactStore, cache_version: str) -> None:
        self.artifact_store = artifact_store
        self.cache_version = cache_version

    def operation_result_key(self, operation: str, cache_key: str) -> str:
        return f"cache/op/{operation}/{cache_key}/result.json"

    def operation_manifest_key(self, operation: str, cache_key: str) -> str:
        return f"cache/op/{operation}/{cache_key}/manifest.json"

    def operation_artifact_key(self, operation: str, cache_key: str, relative_path: str) -> str:
        return f"cache/op/{operation}/{cache_key}/{relative_path}"

    def step_manifest_key(self, job_id: str, step_hash: str) -> str:
        return f"cache/steps/{job_id}/{step_hash}/manifest.json"

    def step_artifact_key(self, job_id: str, step_hash: str, relative_path: str) -> str:
        return f"cache/steps/{job_id}/{step_hash}/{relative_path}"

    def job_artifact_key(self, job_id: str, kind: str, relative_path: str) -> str:
        return f"jobs/{job_id}/{kind}/{relative_path}"

    def save_operation_result(self, operation: str, cache_key: str, payload: dict[str, Any]) -> None:
        self.artifact_store.upload_json(self.operation_result_key(operation, cache_key), payload)

    def load_operation_result(self, operation: str, cache_key: str) -> dict[str, Any] | None:
        key = self.operation_result_key(operation, cache_key)
        if not self.artifact_store.exists(key):
            return None
        return self.artifact_store.download_json(key)

    def save_operation_bundle(
        self,
        operation: str,
        cache_key: str,
        payload: dict[str, Any],
        artifact_paths: list[str],
        file_manager: FileManager,
    ) -> dict[str, Any]:
        manifest_artifacts: list[StepArtifact] = []
        for path in artifact_paths:
            kind, relative_path = file_manager.classify_path(path)
            cache_artifact_key = self.operation_artifact_key(operation, cache_key, relative_path)
            self.artifact_store.upload_file(cache_artifact_key, path)
            manifest_artifacts.append(
                StepArtifact(
                    relative_path=relative_path,
                    kind=kind,
                    cache_key=cache_artifact_key,
                    job_key="",
                    sha256=hash_file(path),
                )
            )
        manifest = {
            "payload": self._serialize_value(payload, file_manager),
            "artifacts": [asdict(artifact) for artifact in manifest_artifacts],
        }
        self.artifact_store.upload_json(self.operation_manifest_key(operation, cache_key), manifest)
        return manifest

    def load_operation_bundle(
        self,
        operation: str,
        cache_key: str,
        file_manager: FileManager,
    ) -> dict[str, Any] | None:
        manifest_key = self.operation_manifest_key(operation, cache_key)
        if not self.artifact_store.exists(manifest_key):
            return None
        manifest = self.artifact_store.download_json(manifest_key)
        for artifact in manifest.get("artifacts", []):
            self.artifact_store.download_file(
                artifact["cache_key"],
                file_manager.resolve_artifact_path(artifact["kind"], artifact["relative_path"]),
            )
        return self._deserialize_value(manifest.get("payload", {}), file_manager)

    def step_exists(self, job_id: str, step_hash: str) -> bool:
        return self.artifact_store.exists(self.step_manifest_key(job_id, step_hash))

    def save_step_result(
        self,
        job_id: str,
        step_name: str,
        step_hash: str,
        result: StepResult,
        file_manager: FileManager,
    ) -> StepManifest:
        manifest_artifacts: list[StepArtifact] = []
        for path in self._flatten_artifact_paths(result.artifacts):
            kind, relative_path = file_manager.classify_path(path)
            cache_key = self.step_artifact_key(job_id, step_hash, relative_path)
            job_key = self.job_artifact_key(job_id, kind, relative_path)
            self.artifact_store.upload_file(cache_key, path)
            self.artifact_store.upload_file(job_key, path)
            manifest_artifacts.append(
                StepArtifact(
                    relative_path=relative_path,
                    kind=kind,
                    cache_key=cache_key,
                    job_key=job_key,
                    sha256=hash_file(path),
                )
            )

        manifest = StepManifest(
            step_name=step_name,
            step_hash=step_hash,
            context_patch=self._serialize_value(result.context_patch, file_manager),
            artifacts=manifest_artifacts,
            metadata=result.metadata,
        )
        self.artifact_store.upload_json(self.step_manifest_key(job_id, step_hash), manifest.to_dict())
        return manifest

    def load_step_result(self, job_id: str, step_hash: str, file_manager: FileManager) -> StepManifest | None:
        manifest_key = self.step_manifest_key(job_id, step_hash)
        if not self.artifact_store.exists(manifest_key):
            return None
        manifest = StepManifest.from_dict(self.artifact_store.download_json(manifest_key))
        for artifact in manifest.artifacts:
            self.artifact_store.download_file(
                artifact.cache_key,
                file_manager.resolve_artifact_path(artifact.kind, artifact.relative_path),
            )
        manifest.context_patch = self._deserialize_value(manifest.context_patch, file_manager)
        return manifest

    def _flatten_artifact_paths(self, artifacts: dict[str, str | list[str]]) -> list[str]:
        flattened: list[str] = []
        for value in artifacts.values():
            if isinstance(value, list):
                flattened.extend(value)
            else:
                flattened.append(value)
        return flattened

    def _serialize_value(self, value: Any, file_manager: FileManager) -> Any:
        if isinstance(value, dict):
            return {key: self._serialize_value(item, file_manager) for key, item in value.items()}
        if isinstance(value, list):
            return [self._serialize_value(item, file_manager) for item in value]
        if isinstance(value, str):
            try:
                kind, relative_path = file_manager.classify_path(value)
            except Exception:
                return value
            return {ARTIFACT_TOKEN: {"kind": kind, "relative_path": relative_path}}
        return value

    def _deserialize_value(self, value: Any, file_manager: FileManager) -> Any:
        if isinstance(value, dict) and ARTIFACT_TOKEN in value:
            payload = value[ARTIFACT_TOKEN]
            return str(file_manager.resolve_artifact_path(payload["kind"], payload["relative_path"]))
        if isinstance(value, dict):
            return {key: self._deserialize_value(item, file_manager) for key, item in value.items()}
        if isinstance(value, list):
            return [self._deserialize_value(item, file_manager) for item in value]
        return value
