from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from enum import Enum
from typing import Any


def utcnow() -> datetime:
    return datetime.now(UTC)


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class JobRecord:
    id: str
    status: JobStatus = JobStatus.PENDING
    pipeline_type: str = "dubbing"
    payload: dict[str, Any] = field(default_factory=dict)
    input_path: str | None = None
    input_uri: str | None = None
    output_path: str | None = None
    source_sha256: str = ""
    pid: int | None = None
    worker_id: str | None = None
    lease_expires_at: datetime | None = None
    cancel_requested: bool = False
    attempt_count: int = 0
    progress: int = 0
    step_index: int = 0
    total_steps: int = 0
    current_step: str | None = None
    log: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        for key in ("lease_expires_at", "created_at", "started_at", "finished_at", "updated_at"):
            value = payload[key]
            payload[key] = value.isoformat() if value else None
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobRecord":
        payload = dict(data)
        payload["status"] = JobStatus(payload.get("status", JobStatus.PENDING.value))
        for key in ("lease_expires_at", "created_at", "started_at", "finished_at", "updated_at"):
            value = payload.get(key)
            if value:
                payload[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
            else:
                payload[key] = None
        payload.setdefault("payload", {})
        payload.setdefault("metadata", {})
        allowed_fields = {item.name for item in fields(cls)}
        payload = {key: value for key, value in payload.items() if key in allowed_fields}
        return cls(**payload)


@dataclass(slots=True)
class StepArtifact:
    relative_path: str
    kind: str
    cache_key: str
    job_key: str
    sha256: str


@dataclass(slots=True)
class StepResult:
    context_patch: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str | list[str]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StepManifest:
    step_name: str
    step_hash: str
    context_patch: dict[str, Any] = field(default_factory=dict)
    artifacts: list[StepArtifact] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_name": self.step_name,
            "step_hash": self.step_hash,
            "context_patch": self.context_patch,
            "artifacts": [asdict(item) for item in self.artifacts],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StepManifest":
        return cls(
            step_name=data["step_name"],
            step_hash=data["step_hash"],
            context_patch=data.get("context_patch", {}),
            artifacts=[StepArtifact(**item) for item in data.get("artifacts", [])],
            metadata=data.get("metadata", {}),
        )
