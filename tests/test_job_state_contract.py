from __future__ import annotations

import unittest
from datetime import timedelta
from unittest.mock import patch

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


class TestStateTransitions(unittest.TestCase):
    def test_done_cannot_complete_again(self) -> None:
        services = make_services(make_test_root("contract-done-complete"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        services.job_manager.complete_job(job.id, "output.mp4", worker_id="worker-a")

        with self.assertRaises(IllegalStateTransition):
            services.job_manager.complete_job(job.id, "output2.mp4", worker_id="worker-a")

    def test_done_cannot_fail(self) -> None:
        services = make_services(make_test_root("contract-done-fail"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        services.job_manager.complete_job(job.id, "output.mp4", worker_id="worker-a")

        with self.assertRaises(IllegalStateTransition):
            services.job_manager.fail_job(job.id, "late failure", worker_id="worker-a")

    def test_failed_cannot_complete(self) -> None:
        services = make_services(make_test_root("contract-failed-complete"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        services.job_manager.fail_job(job.id, "failure", worker_id="worker-a")

        with self.assertRaises(IllegalStateTransition):
            services.job_manager.complete_job(job.id, "output.mp4", worker_id="worker-a")

    def test_cancelled_cannot_complete(self) -> None:
        services = make_services(make_test_root("contract-cancelled-complete"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        services.job_manager.fail_job(job.id, "cancelled", cancelled=True, worker_id="worker-a")

        with self.assertRaises(IllegalStateTransition):
            services.job_manager.complete_job(job.id, "output.mp4", worker_id="worker-a")


class TestOwnershipGuards(unittest.TestCase):
    def test_only_system_can_do_running_to_pending(self) -> None:
        services = make_services(make_test_root("contract-running-to-pending"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)

        # Verify that only release_stale_leases (system logic) transitions RUNNING -> PENDING
        # (There is no API or worker method in JobManager to manually revert RUNNING to PENDING)
        from core.job_manager import _assert_transition
        record = services.job_manager.repository.get_job(job.id)
        # RUNNING -> PENDING is allowed in model transitions for system use
        self.assertTrue(record.status.can_transition_to(JobStatus.PENDING))
        # But DONE -> PENDING is strictly illegal
        record.status = JobStatus.DONE
        with self.assertRaises(IllegalStateTransition):
            _assert_transition(record, JobStatus.PENDING)


class TestInvariants(unittest.TestCase):
    def test_terminal_always_has_finished_at(self) -> None:
        services = make_services(make_test_root("contract-terminal-finished-at"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        
        completed = services.job_manager.complete_job(job.id, "output.mp4", worker_id="worker-a")
        self.assertIsNotNone(completed.finished_at)

        job2 = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash2")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        failed = services.job_manager.fail_job(job2.id, "failure", worker_id="worker-a")
        self.assertIsNotNone(failed.finished_at)

    def test_terminal_clears_worker_pid_lease(self) -> None:
        services = make_services(make_test_root("contract-terminal-clears"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        services.job_manager.set_pid(job.id, 1234)

        completed = services.job_manager.complete_job(job.id, "output.mp4", worker_id="worker-a")
        self.assertIsNone(completed.worker_id)
        self.assertIsNone(completed.pid)
        self.assertIsNone(completed.lease_expires_at)

    def test_done_sets_progress_100(self) -> None:
        services = make_services(make_test_root("contract-done-progress"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        
        completed = services.job_manager.complete_job(job.id, "output.mp4", worker_id="worker-a")
        self.assertEqual(completed.progress, 100)

    def test_terminal_rejects_update_progress(self) -> None:
        services = make_services(make_test_root("contract-terminal-progress-freeze"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        services.job_manager.complete_job(job.id, "output.mp4", worker_id="worker-a")

        res = services.job_manager.update_progress(
            job.id,
            worker_id="worker-a",
            step_index=2,
            total_steps=5,
            current_step="dubbing",
            progress=40
        )
        self.assertIsNone(res)


class TestZombiePrevention(unittest.TestCase):
    def test_overlong_job_force_failed(self) -> None:
        services = make_services(make_test_root("contract-overlong"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)

        # Mock started_at to be overlong
        repository = services.job_manager.repository
        repository._records[job.id].started_at = utcnow() - timedelta(seconds=7200)

        count = services.job_manager.fail_overlong_jobs(max_duration_seconds=3600)
        self.assertEqual(count, 1)

        refreshed = services.job_manager.get_job(job.id)
        self.assertEqual(refreshed.status, JobStatus.FAILED)
        self.assertEqual(refreshed.error_detail.code, "MAX_DURATION_EXCEEDED")

    def test_retry_creates_new_job_not_resurrect(self) -> None:
        services = make_services(make_test_root("contract-retry-clone"))
        job = services.job_manager.create_job(
            pipeline_type="dubbing",
            source_sha256="hash",
            payload={"test": "data"},
            input_path="input.mp4"
        )
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        services.job_manager.fail_job(job.id, "failure", worker_id="worker-a")

        # Simulate api retry endpoint logic
        old = services.job_manager.get_job(job.id)
        self.assertEqual(old.status, JobStatus.FAILED)

        new_job = services.job_manager.create_job(
            pipeline_type=old.pipeline_type,
            source_sha256=old.source_sha256,
            payload=dict(old.payload),
            input_path=old.input_path,
            input_uri=old.input_uri,
            metadata={**old.metadata, "retry_of": old.id, "retry_count": old.metadata.get("retry_count", 0) + 1}
        )

        self.assertNotEqual(new_job.id, old.id)
        self.assertEqual(new_job.status, JobStatus.PENDING)
        self.assertEqual(new_job.metadata["retry_of"], old.id)


class TestRaceConditions(unittest.TestCase):
    def test_stale_worker_complete_after_lease_expired(self) -> None:
        services = make_services(make_test_root("contract-stale-complete-expired"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)

        # Mock lease expiration and release stale lease
        repository = services.job_manager.repository
        repository._records[job.id].lease_expires_at = utcnow() - timedelta(seconds=1)
        services.job_manager.release_stale_leases(max_attempts=3)

        # Worker A tries to complete now
        with self.assertRaises(IllegalStateTransition):
            services.job_manager.complete_job(job.id, "output.mp4", worker_id="worker-a")

    def test_heartbeat_after_terminal_is_noop(self) -> None:
        services = make_services(make_test_root("contract-heartbeat-noop"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        services.job_manager.complete_job(job.id, "output.mp4", worker_id="worker-a")

        res = services.job_manager.heartbeat(job.id, "worker-a", None, 30)
        self.assertIsNone(res)

    def test_release_stale_twice_no_double_terminal(self) -> None:
        services = make_services(make_test_root("contract-release-twice"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)

        repository = services.job_manager.repository
        repository._records[job.id].lease_expires_at = utcnow() - timedelta(seconds=1)

        # First release stale lease moves to FAILED
        count1 = services.job_manager.release_stale_leases(max_attempts=1)
        self.assertEqual(count1, 1)

        # Second release stale lease should do nothing
        count2 = services.job_manager.release_stale_leases(max_attempts=1)
        self.assertEqual(count2, 0)

    def test_fail_overlong_twice_no_double_terminal(self) -> None:
        services = make_services(make_test_root("contract-overlong-twice"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)

        repository = services.job_manager.repository
        repository._records[job.id].started_at = utcnow() - timedelta(seconds=7200)

        count1 = services.job_manager.fail_overlong_jobs(max_duration_seconds=3600)
        self.assertEqual(count1, 1)

        count2 = services.job_manager.fail_overlong_jobs(max_duration_seconds=3600)
        self.assertEqual(count2, 0)


class TestWebhookContract(unittest.TestCase):
    @patch("core.job_manager._dispatch_webhook")
    def test_done_sends_job_completed_once(self, mock_dispatch) -> None:
        services = make_services(make_test_root("contract-webhook-done"))
        services.job_manager.webhooks_enabled = True
        
        job = services.job_manager.create_job(
            pipeline_type="dubbing",
            source_sha256="hash",
            payload={"webhook_url": "http://example.com/webhook"}
        )
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)

        services.job_manager.complete_job(job.id, "output.mp4", worker_id="worker-a")
        
        # Ensure it was called once
        mock_dispatch.assert_called_once()
        args, kwargs = mock_dispatch.call_args
        self.assertEqual(args[0], "http://example.com/webhook")
        self.assertEqual(args[2], "job.completed")

    @patch("core.job_manager._dispatch_webhook")
    def test_failed_sends_job_failed_once(self, mock_dispatch) -> None:
        services = make_services(make_test_root("contract-webhook-failed"))
        services.job_manager.webhooks_enabled = True
        
        job = services.job_manager.create_job(
            pipeline_type="dubbing",
            source_sha256="hash",
            payload={"webhook_url": "http://example.com/webhook"}
        )
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)

        services.job_manager.fail_job(job.id, "failure", worker_id="worker-a")
        
        mock_dispatch.assert_called_once()
        args, kwargs = mock_dispatch.call_args
        self.assertEqual(args[0], "http://example.com/webhook")
        self.assertEqual(args[2], "job.failed")

    @patch("core.job_manager._dispatch_webhook")
    def test_cancelled_sends_job_cancelled_once(self, mock_dispatch) -> None:
        services = make_services(make_test_root("contract-webhook-cancelled"))
        services.job_manager.webhooks_enabled = True
        
        job = services.job_manager.create_job(
            pipeline_type="dubbing",
            source_sha256="hash",
            payload={"webhook_url": "http://example.com/webhook"}
        )
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)

        services.job_manager.fail_job(job.id, "cancelled", cancelled=True, worker_id="worker-a")
        
        mock_dispatch.assert_called_once()
        args, kwargs = mock_dispatch.call_args
        self.assertEqual(args[0], "http://example.com/webhook")
        self.assertEqual(args[2], "job.cancelled")

    @patch("core.job_manager._dispatch_webhook")
    def test_reaper_does_not_resend_terminal_webhook(self, mock_dispatch) -> None:
        services = make_services(make_test_root("contract-webhook-reaper"))
        services.job_manager.webhooks_enabled = True
        
        job = services.job_manager.create_job(
            pipeline_type="dubbing",
            source_sha256="hash",
            payload={"webhook_url": "http://example.com/webhook"}
        )
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)

        # Complete job sends webhook
        services.job_manager.complete_job(job.id, "output.mp4", worker_id="worker-a")
        self.assertEqual(mock_dispatch.call_count, 1)

        # Manually mark terminal_notified as True to simulate successful dispatch completed
        repository = services.job_manager.repository
        repository._records[job.id].terminal_notified = True

        # Call retry_pending_webhooks
        services.job_manager.retry_pending_webhooks()
        
        # Verify it wasn't dispatched again
        self.assertEqual(mock_dispatch.call_count, 1)


if __name__ == "__main__":
    unittest.main()

