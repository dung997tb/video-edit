import unittest

from core.models import JobError, JobErrorCode, JobRecord, JobStatus, utcnow


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

    def test_error_detail_round_trips(self) -> None:
        record = JobRecord(
            id="job-err",
            source_sha256="source-hash",
            error="tts failed",
            error_detail=JobError(
                code=JobErrorCode.TTS_FAILED.value,
                message="tts failed",
                step="tts",
                retriable=True,
            ),
        )

        restored = JobRecord.from_dict(record.to_dict())

        self.assertIsNotNone(restored.error_detail)
        self.assertEqual(restored.error_detail.code, JobErrorCode.TTS_FAILED.value)
        self.assertEqual(restored.error_detail.step, "tts")

    def test_job_error_taxonomy_fields_round_trip(self) -> None:
        error = JobError(
            code=JobErrorCode.UNKNOWN_OPERATION.value,
            message="unsupported operation 'unknown_op'",
            retriable=False,
            stage="build_workflow",
            operation="unknown_op",
        )

        restored = JobError.from_dict(error.to_dict())

        self.assertEqual(restored.code, JobErrorCode.UNKNOWN_OPERATION.value)
        self.assertEqual(restored.stage, "build_workflow")
        self.assertEqual(restored.operation, "unknown_op")
        self.assertFalse(restored.retriable)
