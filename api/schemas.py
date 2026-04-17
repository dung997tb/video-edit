from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CreateJobRequest(BaseModel):
    pipeline_type: str = Field(default="dubbing")
    source_sha256: str | None = None
    input_path: str | None = None
    input_uri: str | None = None
    source_key: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobResponse(BaseModel):
    id: str
    status: str
    pipeline_type: str
    input_path: str | None = None
    input_uri: str | None = None
    output_path: str | None = None
    source_sha256: str
    pid: int | None = None
    worker_id: str | None = None
    lease_expires_at: datetime | None = None
    cancel_requested: bool
    attempt_count: int
    progress: int
    step_index: int
    total_steps: int
    current_step: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CancelJobResponse(BaseModel):
    id: str
    cancel_requested: bool
    status: str


class JobListResponse(BaseModel):
    items: list[JobResponse]
