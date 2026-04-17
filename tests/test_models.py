import unittest

from core.models import JobRecord, JobStatus, utcnow


class JobRecordTests(unittest.TestCase):
    def test_from_dict_ignores_unknown_fields(self) -> None:
        now = utcnow().isoformat()
        record = JobRecord.from_dict(
            {
                "id": "job-1",
                "status": JobStatus.RUNNING.value,
                "payload": {"target_language": "vi"},
                "source_sha256": "source-hash",
                "created_at": now,
                "updated_at": now,
                "surprise_field": "ignore-me",
            }
        )

        self.assertEqual(record.id, "job-1")
        self.assertEqual(record.status, JobStatus.RUNNING)
        self.assertEqual(record.payload["target_language"], "vi")
