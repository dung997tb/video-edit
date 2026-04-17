from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from api.schemas import CancelJobResponse, CreateJobRequest, JobListResponse, JobResponse
from core.cache import sha256_bytes
from core.models import JobStatus
from core.runtime import get_services
from core.source_identity import resolve_source_sha256

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _validate_pipeline_type(pipeline_type: str, services) -> None:
    if pipeline_type not in services.pipeline_builders:
        supported = ", ".join(sorted(services.pipeline_builders.keys()))
        raise HTTPException(status_code=400, detail=f"unsupported pipeline_type '{pipeline_type}'. supported: {supported}")


@router.post("", response_model=JobResponse)
def create_job(request: CreateJobRequest) -> JobResponse:
    services = get_services()
    _validate_pipeline_type(request.pipeline_type, services)
    payload = dict(request.payload)
    if request.source_key:
        payload["source_key"] = request.source_key
    try:
        source_sha256 = resolve_source_sha256(
            source_sha256=request.source_sha256,
            input_path=request.input_path,
            input_uri=request.input_uri,
            source_key=request.source_key,
            artifact_store=services.artifact_store,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = services.job_manager.create_job(
        pipeline_type=request.pipeline_type,
        source_sha256=source_sha256,
        payload=payload,
        input_path=request.input_path,
        input_uri=request.input_uri,
        metadata=request.metadata,
    )
    return JobResponse(**job.to_dict())


@router.post("/upload", response_model=JobResponse)
async def upload_job(
    file: UploadFile = File(...),
    pipeline_type: str = Form(default="dubbing"),
    payload_json: str = Form(default="{}"),
    metadata_json: str = Form(default="{}"),
) -> JobResponse:
    services = get_services()
    _validate_pipeline_type(pipeline_type, services)
    try:
        payload = json.loads(payload_json or "{}")
        metadata = json.loads(metadata_json or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="payload_json and metadata_json must be valid JSON") from exc

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    source_sha256 = sha256_bytes(data)
    filename = Path(file.filename or "input.mp4").name
    source_key = f"uploads/{source_sha256}/{filename}"
    services.artifact_store.upload_bytes(source_key, data)
    payload["source_key"] = source_key
    job = services.job_manager.create_job(
        pipeline_type=pipeline_type,
        source_sha256=source_sha256,
        payload=payload,
        metadata=metadata,
    )
    return JobResponse(**job.to_dict())


@router.get("", response_model=JobListResponse)
def list_jobs(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> JobListResponse:
    services = get_services()
    try:
        parsed_status = JobStatus(status) if status else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid status: {status}") from exc
    jobs = services.job_manager.list_jobs(status=parsed_status, limit=limit)
    return JobListResponse(items=[JobResponse(**job.to_dict()) for job in jobs])


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    services = get_services()
    job = services.job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobResponse(**job.to_dict())


@router.post("/{job_id}/cancel", response_model=CancelJobResponse)
def cancel_job(job_id: str) -> CancelJobResponse:
    services = get_services()
    job = services.job_manager.request_cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return CancelJobResponse(id=job.id, cancel_requested=job.cancel_requested, status=job.status.value)
