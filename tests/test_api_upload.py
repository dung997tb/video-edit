from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    TestClient = None

from api.main import create_app
from tests.helpers import make_services, make_test_root


@unittest.skipIf(TestClient is None, "fastapi stack is not installed")
class ApiUploadTests(unittest.TestCase):
    def _client_and_services(self, *, max_bytes: int = 1024 * 1024):
        services = make_services(make_test_root("api-upload"))
        services.settings.api_auth_enabled = False
        services.settings.api_embedded_worker = False
        services.settings.api_rate_limit_per_minute = 0
        services.settings.api_upload_max_bytes = max_bytes
        services.pipeline_builders = {"low_level": lambda *_args, **_kwargs: None}
        patches = [
            patch("api.main.get_services", return_value=services),
            patch("api.routes.jobs.get_services", return_value=services),
        ]
        for item in patches:
            item.start()

        def stop_patches() -> None:
            for item in reversed(patches):
                item.stop()

        self.addCleanup(stop_patches)
        return TestClient(create_app()), services

    def test_upload_creates_job_successfully(self) -> None:
        client, _services = self._client_and_services()
        content = b"a" * 1024

        response = client.post(
            "/jobs/upload",
            data={"pipeline_type": "low_level", "payload_json": '{"operations":[{"type":"cut"}]}'},
            files={"file": ("clip.mp4", content, "video/mp4")},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["pipeline_type"], "low_level")
        self.assertEqual(data["source_sha256"], hashlib.sha256(content).hexdigest())
        self.assertIn("payload", data)
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)

    def test_upload_exceeds_max_bytes(self) -> None:
        client, _services = self._client_and_services(max_bytes=8)

        response = client.post(
            "/jobs/upload",
            data={"pipeline_type": "low_level", "payload_json": "{}"},
            files={"file": ("clip.mp4", b"123456789", "video/mp4")},
        )

        self.assertEqual(response.status_code, 413)

    def test_upload_empty_file(self) -> None:
        client, _services = self._client_and_services()

        response = client.post(
            "/jobs/upload",
            data={"pipeline_type": "low_level", "payload_json": "{}"},
            files={"file": ("clip.mp4", b"", "video/mp4")},
        )

        self.assertEqual(response.status_code, 400)

    def test_upload_invalid_payload_json(self) -> None:
        client, _services = self._client_and_services()

        response = client.post(
            "/jobs/upload",
            data={"pipeline_type": "low_level", "payload_json": "not json"},
            files={"file": ("clip.mp4", b"data", "video/mp4")},
        )

        self.assertEqual(response.status_code, 400)

    def test_upload_invalid_metadata_json(self) -> None:
        client, _services = self._client_and_services()

        response = client.post(
            "/jobs/upload",
            data={"pipeline_type": "low_level", "payload_json": "{}", "metadata_json": "not json"},
            files={"file": ("clip.mp4", b"data", "video/mp4")},
        )

        self.assertEqual(response.status_code, 400)

    def test_upload_sha256_matches_content(self) -> None:
        client, services = self._client_and_services()
        content = b"video bytes"

        response = client.post(
            "/jobs/upload",
            data={"pipeline_type": "low_level", "payload_json": "{}"},
            files={"file": ("clip.mp4", content, "video/mp4")},
        )

        self.assertEqual(response.status_code, 200)
        job = services.job_manager.get_job(response.json()["id"])
        self.assertIsNotNone(job)
        self.assertEqual(job.source_sha256, hashlib.sha256(content).hexdigest())

    def test_upload_source_key_stored_in_artifact_store(self) -> None:
        client, services = self._client_and_services()
        content = b"artifact content"
        expected_sha256 = hashlib.sha256(content).hexdigest()
        expected_key = f"uploads/{expected_sha256}/clip.mp4"

        response = client.post(
            "/jobs/upload",
            data={"pipeline_type": "low_level", "payload_json": "{}"},
            files={"file": ("clip.mp4", content, "video/mp4")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(services.artifact_store.exists(expected_key))
        self.assertEqual(response.json()["payload"]["source_key"], expected_key)


if __name__ == "__main__":
    unittest.main()
