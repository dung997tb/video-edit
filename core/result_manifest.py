from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.file_manager import FileManager


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
TEXT_EXTENSIONS = {".json", ".srt", ".vtt", ".txt", ".csv"}


@dataclass(slots=True)
class ResultItem:
    id: str
    operation_id: str
    kind: str
    label: str
    path: str
    media_type: str
    artifact_scope: str | None = None
    relative_path: str | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    language: str | None = None
    role: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_result_items(
    *,
    job_id: str,
    node_id: str,
    step_name: str,
    artifacts: dict[str, str | list[str]],
    file_manager: FileManager,
    operation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    metadata = dict(metadata or {})
    op_id = operation_id or metadata.get("operation_id") or node_id
    for artifact_name, value in artifacts.items():
        paths = value if isinstance(value, list) else [value]
        for index, raw_path in enumerate(paths, start=1):
            if raw_path is None:
                continue
            path = str(raw_path)
            scope, relative_path = _classify(path, file_manager)
            item = ResultItem(
                id=f"{job_id}:{node_id}:{artifact_name}:{index}",
                operation_id=str(op_id),
                kind=str(artifact_name),
                label=_label(step_name, artifact_name, index, len(paths)),
                path=path,
                artifact_scope=scope,
                relative_path=relative_path,
                media_type=_media_type(path),
                language=metadata.get("language"),
                role=metadata.get("role") or str(artifact_name),
                metadata={
                    "node_id": node_id,
                    "step_name": step_name,
                },
            )
            items.append(item.to_dict())
    return items


def merge_result_items(existing: list[dict[str, Any]] | None, additions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = list(existing or [])
    seen = {str(item.get("id")) for item in merged}
    for item in additions:
        item_id = str(item.get("id"))
        if item_id not in seen:
            merged.append(item)
            seen.add(item_id)
    return merged


def _classify(path: str, file_manager: FileManager) -> tuple[str | None, str | None]:
    try:
        scope, relative_path = file_manager.classify_path(path)
        return scope, relative_path
    except Exception:
        return None, None


def _media_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in TEXT_EXTENSIONS:
        return "text"
    if Path(path).is_dir():
        return "directory"
    return "file"


def _label(step_name: str, artifact_name: str, index: int, total: int) -> str:
    base = artifact_name.replace("_", " ").strip().title() or step_name.replace("_", " ").title()
    if total <= 1:
        return base
    return f"{base} {index}"
