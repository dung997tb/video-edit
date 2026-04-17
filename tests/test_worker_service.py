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
