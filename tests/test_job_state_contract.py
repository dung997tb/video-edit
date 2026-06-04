from __future__ import annotations

import unittest
from datetime import timedelta

from core.exceptions import IllegalStateTransition
from core.models import JobStatus, utcnow
from core.pipeline import PipelineRunner
from tests.helpers import make_services, make_test_root


class JobStateContractTests(unittest.TestCase):
    def test_pending_to_running_via_claim(self) -> None:
        services = make_services(make_test_root("contract-claim"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")

        claimed = services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)

        self.assertEqual([item.id for item in claimed], [job.id])
        self.assertEqual(claimed[0].status, JobStatus.RUNNING)
        self.assertEqual(claimed[0].worker_id, "worker-a")

    def test_pending_cancel_is_terminal(self) -> None:
        services = make_services(make_test_root("contract-pending-cancel"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")

        cancelled = services.job_manager.request_cancel(job.id)

        self.assertIsNotNone(cancelled)
        self.assertEqual(cancelled.status, JobStatus.CANCELLED)
        self.assertIsNotNone(cancelled.finished_at)
        self.assertIsNone(cancelled.worker_id)
        self.assertIsNone(cancelled.lease_expires_at)
        self.assertIsNone(cancelled.pid)

    def test_running_to_done_sets_progress_and_clears_runtime(self) -> None:
        services = make_services(make_test_root("contract-done"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)

        completed = services.job_manager.complete_job(job.id, "output.mp4", worker_id="worker-a")

        self.assertIsNotNone(completed)
        self.assertEqual(completed.status, JobStatus.DONE)
        self.assertEqual(completed.progress, 100)
        self.assertIsNotNone(completed.finished_at)
        self.assertIsNone(completed.worker_id)
        self.assertIsNone(completed.lease_expires_at)
        self.assertIsNone(completed.pid)

    def test_running_to_failed_and_cancelled(self) -> None:
        services = make_services(make_test_root("contract-fail-cancel"))
        failed_job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash-f")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)

        failed = services.job_manager.fail_job(failed_job.id, "boom", worker_id="worker-a")

        cancelled_job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash-c")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        cancelled = services.job_manager.fail_job(
            cancelled_job.id,
            "cancelled",
            cancelled=True,
            worker_id="worker-a",
        )

        self.assertIsNotNone(failed)
        self.assertEqual(failed.status, JobStatus.FAILED)
        self.assertIsNotNone(cancelled)
        self.assertEqual(cancelled.status, JobStatus.CANCELLED)

    def test_terminal_jobs_do_not_transition_or_update_progress(self) -> None:
        services = make_services(make_test_root("contract-terminal-finality"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        completed = services.job_manager.complete_job(job.id, "output.mp4", worker_id="worker-a")
        self.assertIsNotNone(completed)

        with self.assertRaises(IllegalStateTransition):
            services.job_manager.fail_job(job.id, "late failure", worker_id="worker-a")

        self.assertIsNone(
            services.job_manager.update_progress(
                job.id,
                worker_id="worker-a",
                step_index=1,
                total_steps=1,
                current_step="late",
                progress=1,
            )
        )

        refreshed = services.job_manager.get_job(job.id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.status, JobStatus.DONE)
        self.assertEqual(refreshed.progress, 100)

    def test_heartbeat_does_not_resurrect_terminal_job(self) -> None:
        services = make_services(make_test_root("contract-heartbeat-terminal"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        services.job_manager.complete_job(job.id, "output.mp4", worker_id="worker-a")

        heartbeat = services.job_manager.heartbeat(job.id, "worker-a", None, 30)
        refreshed = services.job_manager.get_job(job.id)

        self.assertIsNone(heartbeat)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.status, JobStatus.DONE)

    def test_stale_worker_cannot_complete_or_fail(self) -> None:
        services = make_services(make_test_root("contract-worker-fencing"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)

        with self.assertRaises(IllegalStateTransition):
            services.job_manager.complete_job(job.id, "output.mp4", worker_id="worker-b")
        with self.assertRaises(IllegalStateTransition):
            services.job_manager.fail_job(job.id, "boom", worker_id="worker-b")

        refreshed = services.job_manager.get_job(job.id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.status, JobStatus.RUNNING)
        self.assertEqual(refreshed.worker_id, "worker-a")

    def test_stale_lease_retries_then_fails_at_max_attempts(self) -> None:
        services = make_services(make_test_root("contract-stale-lease"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        repository = services.job_manager.repository
        repository._records[job.id].lease_expires_at = utcnow() - timedelta(seconds=1)  # type: ignore[attr-defined]

        released = services.job_manager.release_stale_leases(max_attempts=3)
        retried = services.job_manager.get_job(job.id)

        self.assertEqual(released, 1)
        self.assertIsNotNone(retried)
        self.assertEqual(retried.status, JobStatus.PENDING)

        services.job_manager.claim_jobs("worker-b", limit=1, lease_seconds=30)
        repository._records[job.id].lease_expires_at = utcnow() - timedelta(seconds=1)  # type: ignore[attr-defined]
        services.job_manager.release_stale_leases(max_attempts=2)
        failed = services.job_manager.get_job(job.id)

        self.assertIsNotNone(failed)
        self.assertEqual(failed.status, JobStatus.FAILED)
        self.assertIsNotNone(failed.finished_at)
        self.assertEqual(failed.error_detail.code, "MAX_ATTEMPTS_EXCEEDED")

    def test_cancel_requested_plus_stale_lease_goes_cancelled(self) -> None:
        services = make_services(make_test_root("contract-stale-cancel"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        services.job_manager.request_cancel(job.id)
        repository = services.job_manager.repository
        repository._records[job.id].lease_expires_at = utcnow() - timedelta(seconds=1)  # type: ignore[attr-defined]

        services.job_manager.release_stale_leases(max_attempts=3)
        refreshed = services.job_manager.get_job(job.id)

        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.status, JobStatus.CANCELLED)

    def test_build_phase_exception_reaches_failed_terminal_state(self) -> None:
        services = make_services(make_test_root("contract-build-failure"))
        job = services.job_manager.create_job(
            pipeline_type="low_level",
            source_sha256="hash",
            input_uri="https://example.com/input.mp4",
        )
        claimed = services.job_manager.claim_jobs(services.settings.resolved_worker_id, limit=1, lease_seconds=30)[0]

        def failing_builder(_job, _services):
            raise ValueError("unsupported low_level operation 'unknown_op'. supported: cut")

        services.pipeline_builders["low_level"] = failing_builder

        with self.assertRaises(ValueError):
            PipelineRunner(services).run_job(claimed)

        refreshed = services.job_manager.get_job(job.id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.status, JobStatus.FAILED)
        self.assertTrue(refreshed.status.is_terminal)
        self.assertIsNotNone(refreshed.finished_at)
        self.assertEqual(refreshed.error_detail.code, "UNKNOWN_OPERATION")
        self.assertEqual(refreshed.error_detail.operation, "unknown_op")


if __name__ == "__main__":
    unittest.main()
