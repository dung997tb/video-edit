from __future__ import annotations

import threading
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any

from core.models import JobRecord, JobStatus, utcnow


class JobRepository(ABC):
    @abstractmethod
    def create_job(self, record: JobRecord) -> JobRecord:
        raise NotImplementedError

    @abstractmethod
    def get_job(self, job_id: str) -> JobRecord | None:
        raise NotImplementedError

    @abstractmethod
    def list_jobs(self, *, status: JobStatus | None = None, limit: int = 50) -> list[JobRecord]:
        raise NotImplementedError

    @abstractmethod
    def claim_jobs(self, worker_id: str, limit: int, lease_seconds: int) -> list[JobRecord]:
        raise NotImplementedError

    @abstractmethod
    def heartbeat(self, job_id: str, worker_id: str, pid: int | None, lease_seconds: int) -> JobRecord | None:
        raise NotImplementedError

    @abstractmethod
    def set_pid(self, job_id: str, pid: int | None) -> JobRecord | None:
        raise NotImplementedError

    @abstractmethod
    def request_cancel(self, job_id: str) -> JobRecord | None:
        raise NotImplementedError

    @abstractmethod
    def is_cancel_requested(self, job_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def update_progress(
        self,
        job_id: str,
        *,
        step_index: int,
        total_steps: int,
        current_step: str,
        progress: int,
    ) -> JobRecord | None:
        raise NotImplementedError

    @abstractmethod
    def complete_job(self, job_id: str, output_path: str | None, metadata: dict[str, Any] | None = None) -> JobRecord | None:
        raise NotImplementedError

    @abstractmethod
    def fail_job(
        self,
        job_id: str,
        error: str,
        *,
        cancelled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> JobRecord | None:
        raise NotImplementedError

    @abstractmethod
    def release_stale_leases(self) -> int:
        raise NotImplementedError


class InMemoryJobRepository(JobRepository):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, JobRecord] = {}

    def _clone(self, record: JobRecord | None) -> JobRecord | None:
        if record is None:
            return None
        return JobRecord.from_dict(record.to_dict())

    def create_job(self, record: JobRecord) -> JobRecord:
        with self._lock:
            self._records[record.id] = self._clone(record)  # type: ignore[assignment]
            return self._clone(record)  # type: ignore[return-value]

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._clone(self._records.get(job_id))

    def list_jobs(self, *, status: JobStatus | None = None, limit: int = 50) -> list[JobRecord]:
        with self._lock:
            records = sorted(self._records.values(), key=lambda item: item.created_at, reverse=True)
            if status is not None:
                records = [item for item in records if item.status == status]
            return [self._clone(item) for item in records[:limit] if item is not None]

    def claim_jobs(self, worker_id: str, limit: int, lease_seconds: int) -> list[JobRecord]:
        now = utcnow()
        claimed: list[JobRecord] = []
        with self._lock:
            for record in self._records.values():
                if record.cancel_requested:
                    continue
                expired = record.lease_expires_at and record.lease_expires_at <= now
                if record.status == JobStatus.PENDING or (record.status == JobStatus.RUNNING and expired):
                    record.status = JobStatus.RUNNING
                    record.worker_id = worker_id
                    record.lease_expires_at = now + timedelta(seconds=lease_seconds)
                    record.attempt_count += 1
                    record.started_at = record.started_at or now
                    record.updated_at = now
                    claimed.append(self._clone(record))  # type: ignore[arg-type]
                    if len(claimed) >= limit:
                        break
        return [item for item in claimed if item is not None]

    def heartbeat(self, job_id: str, worker_id: str, pid: int | None, lease_seconds: int) -> JobRecord | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None or record.worker_id != worker_id:
                return None
            record.status = JobStatus.RUNNING
            record.pid = pid if pid is not None else record.pid
            record.lease_expires_at = utcnow() + timedelta(seconds=lease_seconds)
            record.updated_at = utcnow()
            return self._clone(record)

    def set_pid(self, job_id: str, pid: int | None) -> JobRecord | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            record.pid = pid
            record.updated_at = utcnow()
            return self._clone(record)

    def request_cancel(self, job_id: str) -> JobRecord | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            if record.status in {JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED}:
                return self._clone(record)
            record.cancel_requested = True
            if record.status == JobStatus.PENDING:
                record.status = JobStatus.CANCELLED
                record.finished_at = utcnow()
                record.worker_id = None
                record.lease_expires_at = None
                record.pid = None
            record.updated_at = utcnow()
            return self._clone(record)

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            record = self._records.get(job_id)
            return bool(record and record.cancel_requested)

    def update_progress(
        self,
        job_id: str,
        *,
        step_index: int,
        total_steps: int,
        current_step: str,
        progress: int,
    ) -> JobRecord | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            record.step_index = step_index
            record.total_steps = total_steps
            record.current_step = current_step
            record.progress = progress
            record.updated_at = utcnow()
            return self._clone(record)

    def complete_job(self, job_id: str, output_path: str | None, metadata: dict[str, Any] | None = None) -> JobRecord | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            record.status = JobStatus.DONE
            record.output_path = output_path
            record.progress = 100
            record.finished_at = utcnow()
            record.lease_expires_at = None
            record.worker_id = None
            record.pid = None
            if metadata:
                record.metadata.update(metadata)
            record.updated_at = utcnow()
            return self._clone(record)

    def fail_job(
        self,
        job_id: str,
        error: str,
        *,
        cancelled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> JobRecord | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            record.status = JobStatus.CANCELLED if cancelled else JobStatus.FAILED
            record.error = error
            record.finished_at = utcnow()
            record.lease_expires_at = None
            record.worker_id = None
            record.pid = None
            if metadata:
                record.metadata.update(metadata)
            record.updated_at = utcnow()
            return self._clone(record)

    def release_stale_leases(self) -> int:
        now = utcnow()
        count = 0
        with self._lock:
            for record in self._records.values():
                if record.status == JobStatus.RUNNING and record.lease_expires_at and record.lease_expires_at <= now:
                    count += 1
                    record.worker_id = None
                    record.lease_expires_at = None
                    record.pid = None
                    record.status = JobStatus.CANCELLED if record.cancel_requested else JobStatus.PENDING
                    record.updated_at = now
                    if record.cancel_requested:
                        record.finished_at = now
        return count


class SupabaseJobRepository(JobRepository):
    def __init__(self, client: Any, table: str = "jobs") -> None:
        self.client = client
        self.table = table

    def create_job(self, record: JobRecord) -> JobRecord:
        response = self.client.table(self.table).insert(record.to_dict()).execute()
        return JobRecord.from_dict(response.data[0])

    def get_job(self, job_id: str) -> JobRecord | None:
        response = self.client.table(self.table).select("*").eq("id", job_id).limit(1).execute()
        if not response.data:
            return None
        return JobRecord.from_dict(response.data[0])

    def list_jobs(self, *, status: JobStatus | None = None, limit: int = 50) -> list[JobRecord]:
        query = self.client.table(self.table).select("*").order("created_at", desc=True).limit(limit)
        if status is not None:
            query = query.eq("status", status.value)
        response = query.execute()
        return [JobRecord.from_dict(item) for item in (response.data or [])]

    def claim_jobs(self, worker_id: str, limit: int, lease_seconds: int) -> list[JobRecord]:
        response = self.client.rpc(
            "claim_jobs",
            {
                "p_worker_id": worker_id,
                "p_limit": limit,
                "p_lease_seconds": lease_seconds,
            },
        ).execute()
        return [JobRecord.from_dict(item) for item in (response.data or [])]

    def heartbeat(self, job_id: str, worker_id: str, pid: int | None, lease_seconds: int) -> JobRecord | None:
        expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        response = (
            self.client.table(self.table)
            .update(
                {
                    "status": JobStatus.RUNNING.value,
                    "worker_id": worker_id,
                    "pid": pid,
                    "lease_expires_at": expires_at.isoformat(),
                    "updated_at": utcnow().isoformat(),
                }
            )
            .eq("id", job_id)
            .eq("worker_id", worker_id)
            .execute()
        )
        if not response.data:
            return None
        return JobRecord.from_dict(response.data[0])

    def set_pid(self, job_id: str, pid: int | None) -> JobRecord | None:
        response = self.client.table(self.table).update({"pid": pid, "updated_at": utcnow().isoformat()}).eq("id", job_id).execute()
        if not response.data:
            return None
        return JobRecord.from_dict(response.data[0])

    def request_cancel(self, job_id: str) -> JobRecord | None:
        try:
            response = self.client.rpc("request_cancel_job", {"p_job_id": job_id}).execute()
            if response.data:
                return JobRecord.from_dict(response.data[0])
        except Exception:
            # Backward compatibility for databases that have not applied the new RPC yet.
            pass

        record = self.get_job(job_id)
        if record is None:
            return None
        if record.status in {JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED}:
            return record
        now = utcnow().isoformat()
        pending_cancel = (
            self.client.table(self.table)
            .update(
                {
                    "cancel_requested": True,
                    "status": JobStatus.CANCELLED.value,
                    "finished_at": now,
                    "worker_id": None,
                    "lease_expires_at": None,
                    "pid": None,
                    "updated_at": now,
                }
            )
            .eq("id", job_id)
            .eq("status", JobStatus.PENDING.value)
            .execute()
        )
        if pending_cancel.data:
            return JobRecord.from_dict(pending_cancel.data[0])

        response = (
            self.client.table(self.table)
            .update(
                {
                    "cancel_requested": True,
                    "updated_at": now,
                }
            )
            .eq("id", job_id)
            .execute()
        )
        if not response.data:
            return None
        return JobRecord.from_dict(response.data[0])

    def is_cancel_requested(self, job_id: str) -> bool:
        response = self.client.table(self.table).select("cancel_requested").eq("id", job_id).limit(1).execute()
        return bool(response.data and response.data[0].get("cancel_requested"))

    def update_progress(
        self,
        job_id: str,
        *,
        step_index: int,
        total_steps: int,
        current_step: str,
        progress: int,
    ) -> JobRecord | None:
        response = (
            self.client.table(self.table)
            .update(
                {
                    "step_index": step_index,
                    "total_steps": total_steps,
                    "current_step": current_step,
                    "progress": progress,
                    "updated_at": utcnow().isoformat(),
                }
            )
            .eq("id", job_id)
            .execute()
        )
        if not response.data:
            return None
        return JobRecord.from_dict(response.data[0])

    def complete_job(self, job_id: str, output_path: str | None, metadata: dict[str, Any] | None = None) -> JobRecord | None:
        payload: dict[str, Any] = {
            "status": JobStatus.DONE.value,
            "output_path": output_path,
            "progress": 100,
            "worker_id": None,
            "pid": None,
            "lease_expires_at": None,
            "finished_at": utcnow().isoformat(),
            "updated_at": utcnow().isoformat(),
        }
        if metadata:
            payload["metadata"] = metadata
        response = self.client.table(self.table).update(payload).eq("id", job_id).execute()
        if not response.data:
            return None
        return JobRecord.from_dict(response.data[0])

    def fail_job(
        self,
        job_id: str,
        error: str,
        *,
        cancelled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> JobRecord | None:
        payload: dict[str, Any] = {
            "status": JobStatus.CANCELLED.value if cancelled else JobStatus.FAILED.value,
            "error": error,
            "worker_id": None,
            "pid": None,
            "lease_expires_at": None,
            "finished_at": utcnow().isoformat(),
            "updated_at": utcnow().isoformat(),
        }
        if metadata:
            payload["metadata"] = metadata
        response = self.client.table(self.table).update(payload).eq("id", job_id).execute()
        if not response.data:
            return None
        return JobRecord.from_dict(response.data[0])

    def release_stale_leases(self) -> int:
        response = self.client.rpc("release_stale_leases").execute()
        return int(response.data or 0)


class JobManager:
    def __init__(self, repository: JobRepository) -> None:
        self.repository = repository

    def create_job(
        self,
        *,
        pipeline_type: str,
        source_sha256: str,
        payload: dict[str, Any] | None = None,
        input_path: str | None = None,
        input_uri: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> JobRecord:
        record = JobRecord(
            id=str(uuid.uuid4()),
            pipeline_type=pipeline_type,
            source_sha256=source_sha256,
            payload=payload or {},
            input_path=input_path,
            input_uri=input_uri,
            metadata=metadata or {},
        )
        return self.repository.create_job(record)

    def get_job(self, job_id: str) -> JobRecord | None:
        return self.repository.get_job(job_id)

    def list_jobs(self, *, status: JobStatus | None = None, limit: int = 50) -> list[JobRecord]:
        return self.repository.list_jobs(status=status, limit=limit)

    def claim_jobs(self, worker_id: str, limit: int, lease_seconds: int) -> list[JobRecord]:
        return self.repository.claim_jobs(worker_id, limit, lease_seconds)

    def heartbeat(self, job_id: str, worker_id: str, pid: int | None, lease_seconds: int) -> JobRecord | None:
        return self.repository.heartbeat(job_id, worker_id, pid, lease_seconds)

    def set_pid(self, job_id: str, pid: int | None) -> JobRecord | None:
        return self.repository.set_pid(job_id, pid)

    def request_cancel(self, job_id: str) -> JobRecord | None:
        return self.repository.request_cancel(job_id)

    def is_cancel_requested(self, job_id: str) -> bool:
        return self.repository.is_cancel_requested(job_id)

    def update_progress(
        self,
        job_id: str,
        *,
        step_index: int,
        total_steps: int,
        current_step: str,
        progress: int,
    ) -> JobRecord | None:
        return self.repository.update_progress(
            job_id,
            step_index=step_index,
            total_steps=total_steps,
            current_step=current_step,
            progress=progress,
        )

    def complete_job(self, job_id: str, output_path: str | None, metadata: dict[str, Any] | None = None) -> JobRecord | None:
        return self.repository.complete_job(job_id, output_path, metadata)

    def fail_job(
        self,
        job_id: str,
        error: str,
        *,
        cancelled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> JobRecord | None:
        return self.repository.fail_job(job_id, error, cancelled=cancelled, metadata=metadata)

    def release_stale_leases(self) -> int:
        return self.repository.release_stale_leases()
