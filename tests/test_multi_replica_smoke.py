from __future__ import annotations

import sys
import time
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from core.artifact_store import LocalArtifactStore
from core.batch_engine import WorkerService
from core.cache import CacheManager
from core.job_manager import InMemoryJobRepository, JobManager
from core.models import JobStatus, StepResult, utcnow
from core.process import ProcessRegistry, run_subprocess
from modules.base import BaseModule
from tests.helpers import make_test_root


class LongSubprocessModule(BaseModule):
    NAME = "long_subprocess"

    def execute(self, context, services) -> StepResult:
        output_path = context.file_manager.temp("long-step.txt")
        run_subprocess(
            [sys.executable, "-c", "import time; time.sleep(8)"],
            job_id=context.job_id,
            job_manager=services.job_manager,
            process_registry=services.process_registry,
            cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
            grace_seconds=services.settings.cancel_grace_seconds,
        )
        output_path.write_text("done", encoding="utf-8")
        return StepResult(artifacts={"long": str(output_path)})


class QuickFinalizeModule(BaseModule):
    NAME = "finalize"

    def execute(self, context, services) -> StepResult:
        output_path = context.file_manager.step_file("final")
        output_path.write_text("ok", encoding="utf-8")
        return StepResult(
            context_patch={"output_video": str(output_path)},
            artifacts={"output_video": str(output_path)},
        )


def _make_services(root: Path, repository: InMemoryJobRepository, worker_id: str):
    settings = SimpleNamespace(
        temp_dir=root / "temp",
        output_dir=root / "output",
        logs_dir=root / "logs",
        cache_dir=root / "cache",
        cache_version="test-v1",
        max_workers=1,
        worker_poll_interval_seconds=0.01,
        worker_poll_min_seconds=0.01,
        worker_poll_max_seconds=0.05,
        worker_poll_backoff_factor=1.5,
        job_lease_seconds=1,
        heartbeat_interval_seconds=0.01,
        cancel_grace_seconds=0.1,
        step_retry_attempts=1,
        step_retry_delay_seconds=0.0,
        resolved_worker_id=worker_id,
    )
    artifact_store = LocalArtifactStore(root / "shared-artifacts")
    return SimpleNamespace(
        settings=settings,
        artifact_store=artifact_store,
        cache_manager=CacheManager(artifact_store=artifact_store, cache_version=settings.cache_version),
        job_manager=JobManager(repository),
        process_registry=ProcessRegistry(),
        pipeline_builders={
            "smoke": lambda job, services: [LongSubprocessModule(), QuickFinalizeModule()],
            "quick": lambda job, services: [QuickFinalizeModule()],
        },
    )


class MultiReplicaSmokeTests(unittest.TestCase):
    def test_cancel_flow_with_two_workers(self) -> None:
        root = make_test_root("multi-replica-cancel")
        repository = InMemoryJobRepository()
        services_a = _make_services(root, repository, "worker-a")
        services_b = _make_services(root, repository, "worker-b")
        worker_a = WorkerService(services_a)
        worker_b = WorkerService(services_b)
        try:
            job = services_a.job_manager.create_job(
                pipeline_type="smoke",
                source_sha256="source-hash",
                input_path=str(root / "input.mp4"),
            )
            Path(job.input_path).write_bytes(b"fake")

            worker_a.run_once()
            deadline = time.time() + 3
            while time.time() < deadline:
                current = services_a.job_manager.get_job(job.id)
                if current and current.pid:
                    break
                time.sleep(0.05)

            services_b.job_manager.request_cancel(job.id)

            deadline = time.time() + 5
            while time.time() < deadline:
                worker_a.run_once()
                current = services_a.job_manager.get_job(job.id)
                if current and current.status in {JobStatus.CANCELLED, JobStatus.FAILED, JobStatus.DONE}:
                    break
                time.sleep(0.05)

            refreshed = services_a.job_manager.get_job(job.id)
            self.assertIsNotNone(refreshed)
            self.assertEqual(refreshed.status, JobStatus.CANCELLED)
            self.assertTrue(refreshed.cancel_requested)
        finally:
            worker_a.executor.shutdown(wait=True, cancel_futures=False)
            worker_b.executor.shutdown(wait=True, cancel_futures=False)

    def test_stale_lease_is_reclaimed_by_second_worker(self) -> None:
        root = make_test_root("multi-replica-reclaim")
        repository = InMemoryJobRepository()
        services_a = _make_services(root, repository, "worker-a")
        services_b = _make_services(root, repository, "worker-b")
        worker_b = WorkerService(services_b)
        try:
            job = services_a.job_manager.create_job(
                pipeline_type="quick",
                source_sha256="source-hash",
                input_path=str(root / "input.mp4"),
            )
            Path(job.input_path).write_bytes(b"fake")
            claimed = services_a.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=1)[0]

            # Force a stale lease in the past so worker-b can reclaim.
            repository._records[claimed.id].lease_expires_at = utcnow() - timedelta(seconds=2)  # type: ignore[attr-defined]

            deadline = time.time() + 3
            while time.time() < deadline:
                worker_b.run_once()
                refreshed = services_b.job_manager.get_job(job.id)
                if refreshed and refreshed.status == JobStatus.DONE:
                    break
                time.sleep(0.05)

            refreshed = services_b.job_manager.get_job(job.id)
            self.assertIsNotNone(refreshed)
            self.assertEqual(refreshed.status, JobStatus.DONE)
            self.assertEqual(refreshed.attempt_count, 2)
        finally:
            worker_b.executor.shutdown(wait=True, cancel_futures=False)
