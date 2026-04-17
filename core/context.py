from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.file_manager import FileManager


@dataclass(slots=True)
class PipelineContext:
    job_id: str
    pipeline_type: str
    input_video: str
    source_sha256: str
    file_manager: FileManager
    artifact_store: Any
    audio_path: str | None = None
    transcript_path: str | None = None
    translation_path: str | None = None
    subtitle_path: str | None = None
    burned_video: str | None = None
    synced_audio: str | None = None
    mixed_audio: str | None = None
    output_video: str | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    translated_segments: list[dict[str, Any]] = field(default_factory=list)
    tts_segments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    step_logs: list[str] = field(default_factory=list)

    def update(self, patch: dict[str, Any]) -> None:
        for key, value in patch.items():
            if key in {"metadata", "state"} and isinstance(getattr(self, key, None), dict) and isinstance(value, dict):
                merged = dict(getattr(self, key))
                merged.update(value)
                setattr(self, key, merged)
                continue
            setattr(self, key, value)


class BaseAIModule:
    NAME = "base-ai-module"

    def __init__(self, context: PipelineContext) -> None:
        self.context = context
