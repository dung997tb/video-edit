from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.job_manager import SupabaseJobRepository
from core.models import JobRecord, JobStatus, utcnow


def _record_dict(
    *,
    job_id: str = "job-1",
    status: JobStatus = JobStatus.PENDING,
    output_path: str | None = None,
    progress: int = 0,
) -> dict:
    record = JobRecord(
        id=job_id,
        status=status,
        pipeline_type="dubbing",
        source_sha256="source-hash",
        output_path=output_path,
        progress=progress,
    )
    if status in {JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED}:
        record.finished_at = utcnow()
    return record.to_dict()


class SupabaseJobRepositoryTests(unittest.TestCase):
    def test_create_job_calls_insert(self) -> None:
        client = MagicMock()
        table = client.table.return_value
        insert_query = table.insert.return_value
        record = JobRecord(id="job-1", pipeline_type="dubbing", source_sha256="source-hash")
        insert_query.execute.return_value = SimpleNamespace(data=[record.to_dict()])
        repo = SupabaseJobRepository(client, table="jobs")

        created = repo.create_job(record)

        client.table.assert_called_once_with("jobs")
        table.insert.assert_called_once_with(record.to_dict())
        self.assertEqual(created.id, record.id)

    def test_get_job_returns_none_when_not_found(self) -> None:
        client = MagicMock()
        table = client.table.return_value
        query = table.select.return_value
        query.eq.return_value = query
        query.limit.return_value = query
        query.execute.return_value = SimpleNamespace(data=[])
        repo = SupabaseJobRepository(client, table="jobs")

        result = repo.get_job("missing")

        self.assertIsNone(result)
        table.select.assert_called_once_with("*")

    def test_claim_jobs_calls_rpc(self) -> None:
        client = MagicMock()
        rpc_query = client.rpc.return_value
        rpc_query.execute.return_value = SimpleNamespace(data=[_record_dict()])
        repo = SupabaseJobRepository(client, table="jobs")

        claimed = repo.claim_jobs("worker-a", limit=2, lease_seconds=30)

        client.rpc.assert_called_once_with(
            "claim_jobs",
            {"p_worker_id": "worker-a", "p_limit": 2, "p_lease_seconds": 30},
        )
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].id, "job-1")

    def test_complete_job_updates_status_done(self) -> None:
        client = MagicMock()
        table = client.table.return_value
        query = table.update.return_value
        query.eq.return_value = query
        query.execute.return_value = SimpleNamespace(
            data=[_record_dict(status=JobStatus.DONE, output_path="output.mp4", progress=100)]
        )
        repo = SupabaseJobRepository(client, table="jobs")

        completed = repo.complete_job("job-1", "output.mp4")

        payload = table.update.call_args.args[0]
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["output_path"], "output.mp4")
        self.assertEqual(payload["progress"], 100)
        self.assertIn("finished_at", payload)
        self.assertEqual(completed.status, JobStatus.DONE)

    def test_request_cancel_fallback_to_direct_update(self) -> None:
        client = MagicMock()
        client.rpc.return_value.execute.side_effect = RuntimeError("rpc missing")

        select_table = MagicMock()
        select_query = select_table.select.return_value
        select_query.eq.return_value = select_query
        select_query.limit.return_value = select_query
        select_query.execute.return_value = SimpleNamespace(data=[_record_dict(status=JobStatus.PENDING)])

        update_table = MagicMock()
        update_query = update_table.update.return_value
        update_query.eq.return_value = update_query
        update_query.execute.return_value = SimpleNamespace(data=[_record_dict(status=JobStatus.CANCELLED)])

        client.table.side_effect = [select_table, update_table]
        repo = SupabaseJobRepository(client, table="jobs")

        cancelled = repo.request_cancel("job-1")

        client.rpc.assert_called_once_with("request_cancel_job", {"p_job_id": "job-1"})
        payload = update_table.update.call_args.args[0]
        self.assertTrue(payload["cancel_requested"])
        self.assertEqual(payload["status"], "cancelled")
        self.assertEqual(cancelled.status, JobStatus.CANCELLED)


if __name__ == "__main__":
    unittest.main()
