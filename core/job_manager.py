from __future__ import annotations

import threading
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from core.logger import logger
from core.metrics import metrics
from core.exceptions import IllegalStateTransition
from core.models import JobError, JobRecord, JobStatus, utcnow


def _assert_transition(record: JobRecord, target: JobStatus) -> None:
    if not record.status.can_transition_to(target):
        raise IllegalStateTransition(
            f"Chuyển đổi trạng thái không hợp lệ cho Job {record.id}: {record.status.value} -> {target.value}"
        )


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
        worker_id: str | None = None,
        step_index: int,
        total_steps: int,
        current_step: str,
        progress: int,
    ) -> JobRecord | None:
        raise NotImplementedError

    @abstractmethod
    def complete_job(
        self,
        job_id: str,
        output_path: str | None,
        metadata: dict[str, Any] | None = None,
        *,
        worker_id: str | None = None,
    ) -> JobRecord | None:
        raise NotImplementedError

    @abstractmethod
    def fail_job(
        self,
        job_id: str,
        error: str,
        *,
        cancelled: bool = False,
        error_detail: JobError | dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        worker_id: str | None = None,
    ) -> JobRecord | None:
        raise NotImplementedError

    @abstractmethod
    def release_stale_leases(self, *, max_attempts: int = 3) -> int:
        raise NotImplementedError

    @abstractmethod
    def fail_overlong_jobs(self, *, max_duration_seconds: int = 3600) -> int:
        raise NotImplementedError

    @abstractmethod
    def mark_webhook_attempt(self, job_id: str, *, success: bool, error: str | None = None) -> JobRecord | None:
        raise NotImplementedError

    @abstractmethod
    def list_pending_webhooks(self, *, limit: int = 50, max_attempts: int = 3) -> list[JobRecord]:
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
            records = sorted(
                self._records.values(),
                key=lambda item: (-int(getattr(item, "priority", 0)), item.created_at),
            )
            for record in records:
                if record.cancel_requested:
                    continue
                if record.status == JobStatus.PENDING:
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
            if record.status.is_terminal:  # Don't resurrect terminal jobs
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
        worker_id: str | None = None,
        step_index: int,
        total_steps: int,
        current_step: str,
        progress: int,
    ) -> JobRecord | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            if record.status.is_terminal:  # Terminal freezes progress
                return None
            if worker_id is not None and record.worker_id != worker_id:
                return None
            record.step_index = step_index
            record.total_steps = total_steps
            record.current_step = current_step
            record.progress = progress
            record.updated_at = utcnow()
            return self._clone(record)

    def complete_job(
        self,
        job_id: str,
        output_path: str | None,
        metadata: dict[str, Any] | None = None,
        *,
        worker_id: str | None = None,
    ) -> JobRecord | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            _assert_transition(record, JobStatus.DONE)
            if record.worker_id is not None and record.worker_id != worker_id:
                raise IllegalStateTransition(
                    f"Từ chối cập nhật Job {job_id}: worker_id '{worker_id}' không sở hữu job này (sở hữu hiện tại: '{record.worker_id}')"
                )
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
        error_detail: JobError | dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        worker_id: str | None = None,
    ) -> JobRecord | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            target = JobStatus.CANCELLED if cancelled else JobStatus.FAILED
            _assert_transition(record, target)
            if record.worker_id is not None and record.worker_id != worker_id:
                raise IllegalStateTransition(
                    f"Từ chối cập nhật Job {job_id}: worker_id '{worker_id}' không sở hữu job này (sở hữu hiện tại: '{record.worker_id}')"
                )
            record.status = target
            record.error = error
            record.error_detail = _normalize_error_detail(error_detail)
            record.finished_at = utcnow()
            record.lease_expires_at = None
            record.worker_id = None
            record.pid = None
            if metadata:
                record.metadata.update(metadata)
            record.updated_at = utcnow()
            return self._clone(record)

    def release_stale_leases(self, *, max_attempts: int = 3) -> int:
        """Handle jobs whose worker lease has expired.

        RUNNING -> PENDING (retry) when attempt_count < max_attempts.
        RUNNING -> FAILED/CANCELLED (terminal) otherwise.
        This is the ONLY method allowed to perform RUNNING -> PENDING.
        """
        now = utcnow()
        count = 0
        with self._lock:
            for record in self._records.values():
                if record.status == JobStatus.RUNNING and record.lease_expires_at and record.lease_expires_at <= now:
                    count += 1
                    record.worker_id = None
                    record.lease_expires_at = None
                    record.pid = None
                    if record.cancel_requested or record.attempt_count >= max_attempts:
                        record.status = JobStatus.CANCELLED if record.cancel_requested else JobStatus.FAILED
                        record.finished_at = now
                        if not record.cancel_requested:
                            record.error_detail = JobError.max_attempts(max_attempts)
                        record.error = record.error or (
                            "cancelled" if record.cancel_requested
                            else f"max attempts ({max_attempts}) exceeded"
                        )
                    else:
                        record.status = JobStatus.PENDING
                        record.progress = 0
                    record.updated_at = now
        return count

    def fail_overlong_jobs(self, *, max_duration_seconds: int = 3600) -> int:
        """Force-fail jobs running longer than max duration, even with active heartbeat.

        Separate concern from release_stale_leases: that handles dead workers,
        this handles alive-but-stuck workers.
        """
        now = utcnow()
        count = 0
        with self._lock:
            for record in self._records.values():
                if (
                    record.status == JobStatus.RUNNING
                    and record.started_at
                    and (now - record.started_at).total_seconds() >= max_duration_seconds
                ):
                    count += 1
                    record.status = JobStatus.FAILED
                    record.error = f"exceeded max duration ({max_duration_seconds}s)"
                    record.error_detail = JobError(
                        code="MAX_DURATION_EXCEEDED",
                        message=record.error,
                        retriable=False,
                        stage="execution",
                    )
                    record.finished_at = now
                    record.worker_id = None
                    record.lease_expires_at = None
                    record.pid = None
                    record.updated_at = now
        return count

    def mark_webhook_attempt(self, job_id: str, *, success: bool, error: str | None = None) -> JobRecord | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            record.webhook_attempts += 1
            if success:
                record.terminal_notified = True
                record.last_webhook_error = None
            else:
                record.last_webhook_error = error or "delivery failed"
            record.updated_at = utcnow()
            return self._clone(record)

    def list_pending_webhooks(self, *, limit: int = 50, max_attempts: int = 3) -> list[JobRecord]:
        with self._lock:
            records = [
                record
                for record in self._records.values()
                if (
                    record.status.is_terminal
                    and not record.terminal_notified
                    and record.webhook_attempts < max_attempts
                    and (record.metadata.get("webhook_url") or record.payload.get("webhook_url"))
                )
            ]
            records.sort(key=lambda item: item.updated_at)
            return [self._clone(record) for record in records[:limit] if record is not None]


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
            .neq("status", JobStatus.DONE.value)
            .neq("status", JobStatus.FAILED.value)
            .neq("status", JobStatus.CANCELLED.value)
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
        except Exception as exc:
            # Backward compatibility for databases that have not applied the new RPC yet.
            logger.warning(
                "cancel RPC unavailable for job {}, falling back to direct update: {}",
                job_id,
                exc,
            )

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
        worker_id: str | None = None,
        step_index: int,
        total_steps: int,
        current_step: str,
        progress: int,
    ) -> JobRecord | None:
        query = (
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
            .neq("status", JobStatus.DONE.value)
            .neq("status", JobStatus.FAILED.value)
            .neq("status", JobStatus.CANCELLED.value)
        )
        if worker_id is not None:
            query = query.eq("worker_id", worker_id)
        response = query.execute()
        if not response.data:
            return None
        return JobRecord.from_dict(response.data[0])

    def complete_job(
        self,
        job_id: str,
        output_path: str | None,
        metadata: dict[str, Any] | None = None,
        *,
        worker_id: str | None = None,
    ) -> JobRecord | None:
        record = self.get_job(job_id)
        if record is None:
            return None
        _assert_transition(record, JobStatus.DONE)
        if record.worker_id is not None and record.worker_id != worker_id:
            raise IllegalStateTransition(
                f"Từ chối cập nhật Job {job_id}: worker_id '{worker_id}' không sở hữu job này (sở hữu hiện tại: '{record.worker_id}')"
            )

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
        query = self.client.table(self.table).update(payload).eq("id", job_id).eq("status", JobStatus.RUNNING.value)
        if worker_id is not None:
            query = query.eq("worker_id", worker_id)
        response = query.execute()
        if not response.data:
            return None
        return JobRecord.from_dict(response.data[0])

    def fail_job(
        self,
        job_id: str,
        error: str,
        *,
        cancelled: bool = False,
        error_detail: JobError | dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        worker_id: str | None = None,
    ) -> JobRecord | None:
        record = self.get_job(job_id)
        if record is None:
            return None
        target = JobStatus.CANCELLED if cancelled else JobStatus.FAILED
        _assert_transition(record, target)
        if record.worker_id is not None and record.worker_id != worker_id:
            raise IllegalStateTransition(
                f"Từ chối cập nhật Job {job_id}: worker_id '{worker_id}' không sở hữu job này (sở hữu hiện tại: '{record.worker_id}')"
            )

        payload: dict[str, Any] = {
            "status": target.value,
            "error": error,
            "error_detail": _normalize_error_detail(error_detail).to_dict() if error_detail else None,
            "worker_id": None,
            "pid": None,
            "lease_expires_at": None,
            "finished_at": utcnow().isoformat(),
            "updated_at": utcnow().isoformat(),
        }
        if metadata:
            payload["metadata"] = metadata
        query = self.client.table(self.table).update(payload).eq("id", job_id).eq("status", JobStatus.RUNNING.value)
        if worker_id is not None:
            query = query.eq("worker_id", worker_id)
        response = query.execute()
        if not response.data:
            return None
        return JobRecord.from_dict(response.data[0])

    def release_stale_leases(self, *, max_attempts: int = 3) -> int:
        try:
            response = self.client.rpc("release_stale_leases", {"p_max_attempts": max_attempts}).execute()
        except TypeError:
            response = self.client.rpc("release_stale_leases").execute()
        return int(response.data or 0)

    def fail_overlong_jobs(self, *, max_duration_seconds: int = 3600) -> int:
        cutoff = utcnow() - timedelta(seconds=max_duration_seconds)
        now = utcnow().isoformat()
        payload = {
            "status": JobStatus.FAILED.value,
            "error": f"exceeded max duration ({max_duration_seconds}s)",
            "error_detail": JobError(
                code="MAX_DURATION_EXCEEDED",
                message=f"exceeded max duration ({max_duration_seconds}s)",
                retriable=False,
                stage="execution",
            ).to_dict(),
            "worker_id": None,
            "pid": None,
            "lease_expires_at": None,
            "finished_at": now,
            "updated_at": now,
        }
        response = (
            self.client.table(self.table)
            .update(payload)
            .eq("status", JobStatus.RUNNING.value)
            .lte("started_at", cutoff.isoformat())
            .execute()
        )
        return len(response.data or [])

    def mark_webhook_attempt(self, job_id: str, *, success: bool, error: str | None = None) -> JobRecord | None:
        payload: dict[str, Any] = {
            "updated_at": utcnow().isoformat(),
            "last_webhook_error": None if success else (error or "delivery failed"),
        }
        if success:
            payload["terminal_notified"] = True
        record = self.get_job(job_id)
        payload["webhook_attempts"] = int(record.webhook_attempts if record else 0) + 1
        response = self.client.table(self.table).update(payload).eq("id", job_id).execute()
        if not response.data:
            return None
        return JobRecord.from_dict(response.data[0])

    def list_pending_webhooks(self, *, limit: int = 50, max_attempts: int = 3) -> list[JobRecord]:
        response = (
            self.client.table(self.table)
            .select("*")
            .in_("status", [JobStatus.DONE.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value])
            .eq("terminal_notified", False)
            .lt("webhook_attempts", max_attempts)
            .order("updated_at", desc=False)
            .limit(limit)
            .execute()
        )
        jobs = [JobRecord.from_dict(item) for item in (response.data or [])]
        return [
            job
            for job in jobs
            if job.metadata.get("webhook_url") or job.payload.get("webhook_url")
        ]


class JobManager:
    def __init__(self, repository: JobRepository) -> None:
        self.repository = repository
        self.webhooks_enabled = True
        self.webhook_timeout_seconds = 10.0

    def create_job(
        self,
        *,
        pipeline_type: str,
        source_sha256: str,
        payload: dict[str, Any] | None = None,
        input_path: str | None = None,
        input_uri: str | None = None,
        metadata: dict[str, Any] | None = None,
        priority: int | None = None,
        retry_of_job_id: str | None = None,
    ) -> JobRecord:
        payload = payload or {}
        record = JobRecord(
            id=str(uuid.uuid4()),
            pipeline_type=pipeline_type,
            source_sha256=source_sha256,
            priority=_resolve_priority(payload, priority),
            payload=payload,
            input_path=input_path,
            input_uri=input_uri,
            metadata=metadata or {},
            retry_of_job_id=retry_of_job_id,
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
        record = self.repository.request_cancel(job_id)
        if record is not None and record.status == JobStatus.CANCELLED:
            self._notify_terminal(record, event="job.cancelled")
        return record

    def is_cancel_requested(self, job_id: str) -> bool:
        return self.repository.is_cancel_requested(job_id)

    def update_progress(
        self,
        job_id: str,
        *,
        worker_id: str | None = None,
        step_index: int,
        total_steps: int,
        current_step: str,
        progress: int,
    ) -> JobRecord | None:
        return self.repository.update_progress(
            job_id,
            worker_id=worker_id,
            step_index=step_index,
            total_steps=total_steps,
            current_step=current_step,
            progress=progress,
        )

    def complete_job(
        self,
        job_id: str,
        output_path: str | None,
        metadata: dict[str, Any] | None = None,
        *,
        worker_id: str | None = None,
    ) -> JobRecord | None:
        record = self.repository.complete_job(job_id, output_path, metadata, worker_id=worker_id)
        self._notify_terminal(record, event="job.completed")
        return record

    def fail_job(
        self,
        job_id: str,
        error: str,
        *,
        cancelled: bool = False,
        error_detail: JobError | dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        worker_id: str | None = None,
    ) -> JobRecord | None:
        record = self.repository.fail_job(
            job_id,
            error,
            cancelled=cancelled,
            error_detail=error_detail,
            metadata=metadata,
            worker_id=worker_id,
        )
        self._notify_terminal(record, event="job.cancelled" if cancelled else "job.failed")
        return record

    def release_stale_leases(self, *, max_attempts: int = 3) -> int:
        count = self.repository.release_stale_leases(max_attempts=max_attempts)
        if count:
            self.retry_pending_webhooks(max_retries=max_attempts)
        return count

    def fail_overlong_jobs(self, *, max_duration_seconds: int = 3600) -> int:
        count = self.repository.fail_overlong_jobs(max_duration_seconds=max_duration_seconds)
        if count:
            self.retry_pending_webhooks()
        return count

    def retry_pending_webhooks(self, *, max_retries: int = 3, limit: int = 50) -> int:
        count = 0
        for record in self.repository.list_pending_webhooks(limit=limit, max_attempts=max_retries):
            event = {
                JobStatus.DONE: "job.completed",
                JobStatus.FAILED: "job.failed",
                JobStatus.CANCELLED: "job.cancelled",
            }.get(record.status)
            if event:
                self._notify_terminal(record, event=event, emit_metrics=False)
                count += 1
        return count

    def _notify_terminal(self, record: JobRecord | None, *, event: str, emit_metrics: bool = True) -> None:
        if record is None:
            return
        duration = None
        if record.started_at and record.finished_at:
            duration = max((record.finished_at - record.started_at).total_seconds(), 0.0)
        if emit_metrics:
            metrics.terminal(record.pipeline_type, record.status.value, duration)
        if record.terminal_notified:
            return
        webhook_url = record.metadata.get("webhook_url") or record.payload.get("webhook_url")
        if not webhook_url:
            return
        enabled = bool(getattr(self, "webhooks_enabled", True))
        if not enabled:
            return
        timeout = float(getattr(self, "webhook_timeout_seconds", 10.0))
        threading.Thread(
            target=self._dispatch_and_mark_webhook,
            args=(str(webhook_url), record, event, timeout),
            daemon=True,
        ).start()

    def _dispatch_and_mark_webhook(self, url: str, record: JobRecord, event: str, timeout: float) -> None:
        error = _dispatch_webhook(url, record, event, timeout)
        self.repository.mark_webhook_attempt(record.id, success=error is None, error=error)


def _resolve_priority(payload: dict[str, Any], explicit: int | None = None) -> int:
    raw = explicit if explicit is not None else payload.get("priority", 0)
    try:
        return max(0, min(10, int(raw)))
    except (TypeError, ValueError):
        return 0


def _normalize_error_detail(error_detail: JobError | dict[str, Any] | None) -> JobError | None:
    if error_detail is None:
        return None
    if isinstance(error_detail, JobError):
        return error_detail
    return JobError.from_dict(error_detail)


def _dispatch_webhook(url: str, record: JobRecord, event: str, timeout: float) -> str | None:
    import json

    payload = json.dumps(
        {
            "event": event,
            "job_id": record.id,
            "status": record.status.value,
            "output_path": record.output_path,
            "metadata": record.metadata,
            "error": record.error,
            "error_detail": record.error_detail.to_dict() if record.error_detail else None,
        },
        ensure_ascii=True,
    ).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "ai-video-engine-webhook"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout):
            pass
    except (OSError, URLError) as exc:
        logger.warning("webhook dispatch failed for job {} to {}: {}", record.id, url, exc)
        return str(exc)
    return None
