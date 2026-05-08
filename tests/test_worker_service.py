from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.batch_engine import WorkerService


class WorkerServiceTests(unittest.TestCase):
    def test_run_forever_continues_after_transient_iteration_error(self) -> None:
        services = SimpleNamespace(
            settings=SimpleNamespace(
                max_workers=1,
                worker_poll_interval_seconds=0.0,
                worker_poll_min_seconds=0.0,
                worker_poll_max_seconds=0.0,
                worker_poll_backoff_factor=1.5,
                resolved_worker_id="worker-test",
                job_lease_seconds=30,
            ),
            job_manager=SimpleNamespace(
                release_stale_leases=lambda: 0,
                claim_jobs=lambda worker_id, limit, lease_seconds: [],
            ),
        )
        worker = WorkerService(services)
        calls = {"count": 0}

        def fake_run_once() -> None:
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("transient")
            worker.stop()

        with patch.object(worker, "run_once", side_effect=fake_run_once):
            worker.run_forever()

        self.assertEqual(calls["count"], 2)

    def test_poll_interval_backs_off_when_idle(self) -> None:
        services = SimpleNamespace(
            settings=SimpleNamespace(
                max_workers=1,
                worker_poll_interval_seconds=1.0,
                worker_poll_min_seconds=0.2,
                worker_poll_max_seconds=1.0,
                worker_poll_backoff_factor=1.5,
                resolved_worker_id="worker-test",
                job_lease_seconds=30,
            ),
            job_manager=SimpleNamespace(
                release_stale_leases=lambda: 0,
                claim_jobs=lambda worker_id, limit, lease_seconds: [],
            ),
        )
        worker = WorkerService(services)

        self.assertAlmostEqual(worker._current_poll_seconds, 0.2, places=3)  # noqa: SLF001
        worker._adjust_poll_interval(activity=False)  # noqa: SLF001
        self.assertAlmostEqual(worker._current_poll_seconds, 0.3, places=3)  # noqa: SLF001
        worker._adjust_poll_interval(activity=False)  # noqa: SLF001
        self.assertAlmostEqual(worker._current_poll_seconds, 0.45, places=3)  # noqa: SLF001

        worker._adjust_poll_interval(activity=False)  # noqa: SLF001
        worker._adjust_poll_interval(activity=False)  # noqa: SLF001
        worker._adjust_poll_interval(activity=False)  # noqa: SLF001
        self.assertLessEqual(worker._current_poll_seconds, 1.0)  # noqa: SLF001

    def test_poll_interval_resets_when_activity_detected(self) -> None:
        services = SimpleNamespace(
            settings=SimpleNamespace(
                max_workers=1,
                worker_poll_interval_seconds=1.0,
                worker_poll_min_seconds=0.2,
                worker_poll_max_seconds=1.0,
                worker_poll_backoff_factor=1.5,
                resolved_worker_id="worker-test",
                job_lease_seconds=30,
            ),
            job_manager=SimpleNamespace(
                release_stale_leases=lambda: 0,
                claim_jobs=lambda worker_id, limit, lease_seconds: [],
            ),
        )
        worker = WorkerService(services)

        worker._adjust_poll_interval(activity=False)  # noqa: SLF001
        worker._adjust_poll_interval(activity=False)  # noqa: SLF001
        self.assertGreater(worker._current_poll_seconds, 0.2)  # noqa: SLF001

        worker._adjust_poll_interval(activity=True)  # noqa: SLF001
        self.assertAlmostEqual(worker._current_poll_seconds, 0.2, places=3)  # noqa: SLF001
