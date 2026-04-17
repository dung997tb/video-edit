from __future__ import annotations

import unittest
from datetime import timedelta

from core.models import JobStatus, utcnow
from tests.helpers import make_services, make_test_root


class JobManagerTests(unittest.TestCase):
    def test_multi_replica_claims_are_disjoint(self) -> None:
        services = make_services(make_test_root("job-manager-claim"))
        jobs = [
            services.job_manager.create_job(pipeline_type="dubbing", source_sha256=f"hash-{index}")
            for index in range(4)
        ]
        first = services.job_manager.claim_jobs("worker-a", limit=2, lease_seconds=30)
        second = services.job_manager.claim_jobs("worker-b", limit=2, lease_seconds=30)

        self.assertTrue({job.id for job in first}.isdisjoint({job.id for job in second}))
        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 2)
        self.assertEqual({job.id for job in first + second}, {job.id for job in jobs})

    def test_cancel_requested_job_becomes_cancelled_after_stale_lease(self) -> None:
        services = make_services(make_test_root("job-manager-cancel"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash-1")
        claimed = services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)[0]
        services.job_manager.request_cancel(claimed.id)

        repository = services.job_manager.repository
        repository._records[job.id].lease_expires_at = utcnow() - timedelta(seconds=1)  # type: ignore[attr-defined]
        released = services.job_manager.release_stale_leases()
        refreshed = services.job_manager.get_job(job.id)

        self.assertEqual(released, 1)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.status, JobStatus.CANCELLED)
        self.assertTrue(refreshed.cancel_requested)

    def test_pending_job_cancel_is_terminal_and_not_claimed(self) -> None:
        services = make_services(make_test_root("job-manager-pending-cancel"))
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash-2")

        cancelled = services.job_manager.request_cancel(job.id)
        claimed = services.job_manager.claim_jobs("worker-a", limit=10, lease_seconds=30)

        self.assertIsNotNone(cancelled)
        self.assertEqual(cancelled.status, JobStatus.CANCELLED)
        self.assertEqual(claimed, [])

    def test_terminal_states_clear_pid(self) -> None:
        services = make_services(make_test_root("job-manager-terminal-pid"))

        completed_job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash-complete")
        services.job_manager.set_pid(completed_job.id, 12345)
        completed = services.job_manager.complete_job(completed_job.id, "output.mp4")

        failed_job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash-fail")
        services.job_manager.set_pid(failed_job.id, 67890)
        failed = services.job_manager.fail_job(failed_job.id, "boom")

        self.assertIsNotNone(completed)
        self.assertIsNone(completed.pid)
        self.assertIsNotNone(failed)
        self.assertIsNone(failed.pid)
