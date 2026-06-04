from __future__ import annotations

import hashlib
import json
import tempfile
import asyncio
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from api.schemas import CancelJobResponse, CreateJobRequest, JobListResponse, JobResponse
from core.artifact_key import normalize_artifact_key
from core.key_redactor import split_redacted_secrets
from core.metrics import metrics
from core.models import JobStatus
from core.payload_parser import parse_job_payload
from core.runtime import get_services
from core.source_identity import resolve_source_sha256
from core.url_security import validate_url_access

router = APIRouter(prefix="/jobs", tags=["jobs"])
UPLOAD_CHUNK_BYTES = 1024 * 1024


def _validate_pipeline_type(pipeline_type: str, services) -> None:
    if pipeline_type not in services.pipeline_builders:
        supported = ", ".join(sorted(services.pipeline_builders.keys()))
        raise HTTPException(status_code=400, detail=f"unsupported pipeline_type '{pipeline_type}'. supported: {supported}")


def _validate_input_uri(input_uri: str | None, services) -> None:
    allowed = {
        item.strip().lower()
        for item in str(getattr(services.settings, "api_allowed_input_uri_schemes", "http,https")).split(",")
        if item.strip()
    }
    try:
        validate_url_access(
            input_uri,
            allowed_schemes=allowed,
            allow_private_networks=bool(getattr(services.settings, "api_allow_private_network_urls", False)),
            field_name="input_uri",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validate_webhook_urls(payload: dict, metadata: dict, services) -> None:
    allowed = {"http", "https"}
    allow_private = bool(getattr(services.settings, "api_allow_private_network_urls", False))
    for field_name, value in (
        ("payload.webhook_url", payload.get("webhook_url")),
        ("metadata.webhook_url", metadata.get("webhook_url")),
    ):
        try:
            validate_url_access(
                str(value) if value else None,
                allowed_schemes=allowed,
                allow_private_networks=allow_private,
                field_name=field_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validate_low_level_operations(payload: dict) -> None:
    from modules.video.low_level import VIDEO_OPERATION_MODULES

    operations = payload.get("operations")
    if not isinstance(operations, list) or not operations:
        raise HTTPException(status_code=400, detail="low_level pipeline requires at least one operation")
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise HTTPException(status_code=400, detail=f"operation[{index}] must be an object")
        params = operation.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise HTTPException(status_code=400, detail=f"operation[{index}].params must be an object")
        name = str(operation.get("name", operation.get("type", params.get("name", params.get("type", ""))))).strip().lower()
        if not name:
            raise HTTPException(status_code=400, detail=f"operation[{index}]: missing 'name' or 'type'")
        if name not in VIDEO_OPERATION_MODULES:
            supported = ", ".join(sorted(VIDEO_OPERATION_MODULES.keys()))
            raise HTTPException(status_code=400, detail=f"operation[{index}]: unsupported '{name}'. supported: {supported}")


def _job_response(job) -> JobResponse:
    data = job.to_dict()
    status = job.status
    data["is_terminal"] = status.is_terminal
    data["can_cancel"] = status in {JobStatus.PENDING, JobStatus.RUNNING}
    data["can_retry"] = bool(
        status == JobStatus.FAILED
        and job.error_detail is not None
        and job.error_detail.retriable
    )
    return JobResponse(**data)


def _prepare_payload_and_metadata(
    services,
    payload: dict,
    metadata: dict,
    *,
    source_key: str | None = None,
) -> tuple[dict, dict, dict[str, str]]:
    try:
        parsed_payload = parse_job_payload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        if source_key:
            parsed_payload["source_key"] = normalize_artifact_key(source_key)
        elif parsed_payload.get("source_key"):
            parsed_payload["source_key"] = normalize_artifact_key(str(parsed_payload["source_key"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metadata = metadata or {}
    _validate_webhook_urls(parsed_payload, metadata, services)
    redacted_payload, payload_secrets = split_redacted_secrets(parsed_payload)
    redacted_metadata, metadata_secrets = split_redacted_secrets(metadata)
    secrets = {f"payload.{key}": value for key, value in payload_secrets.items()}
    secrets.update({f"metadata.{key}": value for key, value in metadata_secrets.items()})
    return redacted_payload, redacted_metadata, secrets


def _store_job_secrets(services, job_id: str, secrets: dict[str, str]) -> None:
    _ensure_secret_store_supported(services, secrets)
    secret_store = getattr(services, "secret_store", None)
    if secret_store is not None:
        secret_store.put(job_id, secrets)


def _ensure_secret_store_supported(services, secrets: dict[str, str]) -> None:
    if secrets and _requires_persistent_secret_store(services):
        raise HTTPException(
            status_code=500,
            detail=(
                "per-job provider secrets require SECRET_STORE_BACKEND=supabase when "
                "JOB_BACKEND=supabase and API_EMBEDDED_WORKER=false"
            ),
        )


def _requires_persistent_secret_store(services) -> bool:
    settings = services.settings
    return bool(
        getattr(settings, "job_backend", "memory") == "supabase"
        and not getattr(settings, "api_embedded_worker", True)
        and getattr(settings, "secret_store_backend", "memory") != "supabase"
    )


@router.post("", response_model=JobResponse)
def create_job(request: CreateJobRequest) -> JobResponse:
    services = get_services()
    _validate_pipeline_type(request.pipeline_type, services)
    _validate_input_uri(request.input_uri, services)
    if request.input_path and not services.settings.api_allow_input_path:
        raise HTTPException(
            status_code=400,
            detail="input_path is disabled for API requests; use /jobs/upload, input_uri, or source_key",
        )
    payload, metadata, secrets = _prepare_payload_and_metadata(
        services,
        dict(request.payload),
        dict(request.metadata),
        source_key=request.source_key,
    )
    if request.pipeline_type == "low_level":
        _validate_low_level_operations(payload)
    _ensure_secret_store_supported(services, secrets)
    try:
        source_sha256 = resolve_source_sha256(
            source_sha256=request.source_sha256,
            input_path=request.input_path,
            input_uri=request.input_uri,
            source_key=request.source_key,
            artifact_store=services.artifact_store,
            allow_explicit_source_sha256=services.settings.api_allow_client_source_sha256,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = services.job_manager.create_job(
        pipeline_type=request.pipeline_type,
        source_sha256=source_sha256,
        payload=payload,
        input_path=request.input_path,
        input_uri=request.input_uri,
        metadata=metadata,
        priority=request.priority,
    )
    _store_job_secrets(services, job.id, secrets)
    metrics.submitted(job.pipeline_type)
    return _job_response(job)


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
    if not isinstance(payload, dict) or not isinstance(metadata, dict):
        raise HTTPException(status_code=400, detail="payload_json and metadata_json must be JSON objects")
    payload, metadata, secrets = _prepare_payload_and_metadata(services, payload, metadata)
    _ensure_secret_store_supported(services, secrets)

    filename = Path(file.filename or "input.mp4").name
    max_bytes = max(1, int(getattr(services.settings, "api_upload_max_bytes", 536_870_912)))
    source_hasher = hashlib.sha256()
    total_bytes = 0
    suffix = Path(filename).suffix or ".bin"
    staging_path: Path | None = None
    try:
        services.settings.temp_dir.mkdir(parents=True, exist_ok=True)
        staging_file = tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=suffix,
            prefix="upload_",
            dir=str(services.settings.temp_dir),
            delete=False,
        )
        staging_path = Path(staging_file.name)
        try:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"uploaded file exceeds API_UPLOAD_MAX_BYTES ({max_bytes} bytes)",
                    )
                source_hasher.update(chunk)
                staging_file.write(chunk)
        finally:
            staging_file.close()
        if total_bytes <= 0:
            raise HTTPException(status_code=400, detail="uploaded file is empty")
        source_sha256 = source_hasher.hexdigest()
        source_key = f"uploads/{source_sha256}/{filename}"
        await run_in_threadpool(services.artifact_store.upload_file, source_key, str(staging_path))
    finally:
        if staging_path is not None:
            staging_path.unlink(missing_ok=True)
        await file.close()
    payload["source_key"] = normalize_artifact_key(source_key)
    if pipeline_type == "low_level":
        _validate_low_level_operations(payload)
    job = services.job_manager.create_job(
        pipeline_type=pipeline_type,
        source_sha256=source_sha256,
        payload=payload,
        metadata=metadata,
    )
    _store_job_secrets(services, job.id, secrets)
    metrics.submitted(job.pipeline_type)
    return _job_response(job)


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
    return JobListResponse(items=[_job_response(job) for job in jobs])


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    services = get_services()
    job = services.job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_response(job)


@router.post("/{job_id}/retry", response_model=JobResponse)
def retry_job(job_id: str) -> JobResponse:
    services = get_services()
    old = services.job_manager.get_job(job_id)
    if old is None:
        raise HTTPException(status_code=404, detail="job not found")
    if old.status != JobStatus.FAILED:
        raise HTTPException(status_code=409, detail="only failed jobs can be retried")
    if old.error_detail is None or not old.error_detail.retriable:
        raise HTTPException(status_code=409, detail="this failure is not retriable")
    metadata = dict(old.metadata)
    metadata["retry_of"] = old.id
    metadata["retry_count"] = int(metadata.get("retry_count", 0)) + 1
    secret_store = getattr(services, "secret_store", None)
    secrets_to_copy: dict[str, str] = {}
    get_secrets = getattr(secret_store, "get", None)
    if callable(get_secrets):
        existing_secrets = get_secrets(old.id)
        if isinstance(existing_secrets, dict):
            secrets_to_copy = existing_secrets
    _ensure_secret_store_supported(services, secrets_to_copy)
    job = services.job_manager.create_job(
        pipeline_type=old.pipeline_type,
        source_sha256=old.source_sha256,
        payload=dict(old.payload),
        input_path=old.input_path,
        input_uri=old.input_uri,
        metadata=metadata,
        priority=old.priority,
        retry_of_job_id=old.id,
    )
    copy_secrets = getattr(secret_store, "copy", None)
    if callable(copy_secrets):
        copy_secrets(old.id, job.id)
    metrics.submitted(job.pipeline_type)
    return _job_response(job)


@router.get("/{job_id}/stream")
async def stream_job_progress(job_id: str) -> StreamingResponse:
    services = get_services()

    async def event_generator():
        while True:
            job = await run_in_threadpool(services.job_manager.get_job, job_id)
            if job is None:
                yield "event: error\ndata: {\"detail\":\"job not found\"}\n\n"
                break
            data = json.dumps(
                {
                    "id": job.id,
                    "progress": job.progress,
                    "step_index": job.step_index,
                    "total_steps": job.total_steps,
                    "current_step": job.current_step,
                    "status": job.status.value,
                    "error": job.error,
                    "error_detail": job.error_detail.to_dict() if job.error_detail else None,
                },
                ensure_ascii=True,
            )
            yield f"data: {data}\n\n"
            if job.status in {JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED}:
                break
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/{job_id}/cancel", response_model=CancelJobResponse)
def cancel_job(job_id: str) -> CancelJobResponse:
    services = get_services()
    job = services.job_manager.request_cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return CancelJobResponse(id=job.id, cancel_requested=job.cancel_requested, status=job.status.value)
