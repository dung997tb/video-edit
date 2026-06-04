from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    TestClient = None

from api.main import create_app
from core.secrets import InMemorySecretStore
from modules.video.low_level import build_low_level_pipeline
from tests.helpers import make_services, make_test_root


@unittest.skipIf(TestClient is None, "fastapi stack is not installed")
class ApiPayloadIntegrationTests(unittest.TestCase):
    def _client_and_services(self):
        services = make_services(make_test_root("api-payload-integration"))
        services.settings.api_auth_enabled = False
        services.settings.api_embedded_worker = False
        services.settings.api_allow_client_source_sha256 = False
        services.settings.api_rate_limit_per_minute = 0
        services.secret_store = InMemorySecretStore()
        services.pipeline_builders = {"low_level": build_low_level_pipeline}
        patches = [
            patch("api.main.get_services", return_value=services),
            patch("api.routes.jobs.get_services", return_value=services),
        ]
        for item in patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])
        return TestClient(create_app()), services

    def test_structured_payload_is_normalized_before_job_is_stored(self) -> None:
        client, services = self._client_and_services()

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "low_level",
                "input_uri": "https://example.com/video.mp4",
                "payload": {
                    "operations": [
                        {
                            "id": "crop-main",
                            "type": "crop",
                            "params": {"width": 320, "height": 240},
                        }
                    ]
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        job = services.job_manager.get_job(response.json()["id"])
        self.assertIsNotNone(job)
        operation = job.payload["operations"][0]
        self.assertEqual(operation["name"], "crop")
        self.assertEqual(operation["operation_id"], "crop-main")
        self.assertEqual(operation["width"], 320)

    def test_provider_key_is_redacted_in_payload_and_kept_in_secret_store(self) -> None:
        client, services = self._client_and_services()

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "low_level",
                "input_uri": "https://example.com/video.mp4",
                "payload": {
                    "providers": {
                        "tts": {
                            "provider": "elevenlabs",
                            "api_key": "secret-api-key-9999",
                        }
                    },
                    "operations": [{"type": "cut", "params": {"duration": 1}}],
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        job_id = response.json()["id"]
        job = services.job_manager.get_job(job_id)
        self.assertEqual(job.payload["providers"]["tts"]["api_key"], "***9999")
        self.assertEqual(
            services.secret_store.get(job_id, "payload.providers.tts.api_key"),
            "secret-api-key-9999",
        )

    def test_invalid_source_key_returns_400_before_job_created(self) -> None:
        client, services = self._client_and_services()

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "low_level",
                "source_key": "../outside.mp4",
                "payload": {"operations": [{"type": "cut", "params": {"duration": 1}}]},
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(services.job_manager.list_jobs(), [])

    def test_payload_source_key_is_validated_when_present(self) -> None:
        client, services = self._client_and_services()

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "low_level",
                "input_uri": "https://example.com/video.mp4",
                "payload": {
                    "source_key": "C:/outside.mp4",
                    "operations": [{"type": "cut", "params": {"duration": 1}}],
                },
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(services.job_manager.list_jobs(), [])

    def test_private_input_uri_is_rejected_by_default(self) -> None:
        client, services = self._client_and_services()

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "low_level",
                "input_uri": "http://127.0.0.1/video.mp4",
                "payload": {"operations": [{"type": "cut", "params": {"duration": 1}}]},
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(services.job_manager.list_jobs(), [])

    def test_split_worker_supabase_requires_persistent_secret_store(self) -> None:
        client, services = self._client_and_services()
        services.settings.job_backend = "supabase"
        services.settings.api_embedded_worker = False
        services.settings.secret_store_backend = "memory"

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "low_level",
                "input_uri": "https://example.com/video.mp4",
                "payload": {
                    "providers": {"tts": {"provider": "elevenlabs", "api_key": "secret-api-key-9999"}},
                    "operations": [{"type": "cut", "params": {"duration": 1}}],
                },
            },
        )

        self.assertEqual(response.status_code, 500)
        self.assertIn("SECRET_STORE_BACKEND=supabase", response.json()["detail"])
        self.assertEqual(services.job_manager.list_jobs(), [])

    def test_payload_time_range_cascades_to_operation(self) -> None:
        client, services = self._client_and_services()

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "low_level",
                "input_uri": "https://example.com/video.mp4",
                "payload": {
                    "time_range": {"start": 5, "duration": 12},
                    "operations": [{"type": "cut", "params": {}}],
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        job = services.job_manager.get_job(response.json()["id"])
        operation = job.payload["operations"][0]
        self.assertEqual(operation["start"], 5.0)
        self.assertEqual(operation["duration"], 12.0)
        self.assertEqual(operation["end"], 17.0)

    def test_unknown_low_level_operation_returns_400_before_job_created(self) -> None:
        client, services = self._client_and_services()

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "low_level",
                "input_uri": "https://example.com/video.mp4",
                "payload": {"operations": [{"type": "unknown_op", "params": {}}]},
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(services.job_manager.list_jobs(), [])

    def test_empty_low_level_operations_returns_400(self) -> None:
        client, services = self._client_and_services()

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "low_level",
                "input_uri": "https://example.com/video.mp4",
                "payload": {"operations": []},
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(services.job_manager.list_jobs(), [])

    def test_job_response_includes_client_actions(self) -> None:
        client, _services = self._client_and_services()

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "low_level",
                "input_uri": "https://example.com/video.mp4",
                "payload": {"operations": [{"type": "cut", "params": {"duration": 1}}]},
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["is_terminal"])
        self.assertTrue(payload["can_cancel"])
        self.assertFalse(payload["can_retry"])

    def test_retry_failed_retriable_job_clones_payload(self) -> None:
        client, services = self._client_and_services()
        job = services.job_manager.create_job(
            pipeline_type="low_level",
            source_sha256="hash",
            input_uri="https://example.com/video.mp4",
            payload={"operations": [{"type": "cut", "params": {"duration": 1}}]},
        )
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        services.job_manager.fail_job(
            job.id,
            "temporary",
            error_detail={"code": "TTS_FAILED", "message": "temporary", "retriable": True},
            worker_id="worker-a",
        )

        response = client.post(f"/jobs/{job.id}/retry")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotEqual(payload["id"], job.id)
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(payload["metadata"]["retry_of"], job.id)
        original = services.job_manager.get_job(job.id)
        self.assertEqual(original.status.value, "failed")

    def test_retry_failed_retriable_job_copies_provider_secret(self) -> None:
        client, services = self._client_and_services()

        create_response = client.post(
            "/jobs",
            json={
                "pipeline_type": "low_level",
                "input_uri": "https://example.com/video.mp4",
                "payload": {
                    "providers": {"tts": {"provider": "elevenlabs", "api_key": "retry-secret-1234"}},
                    "operations": [{"type": "cut", "params": {"duration": 1}}],
                },
            },
        )
        self.assertEqual(create_response.status_code, 200)
        original_job_id = create_response.json()["id"]
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        services.job_manager.fail_job(
            original_job_id,
            "temporary",
            error_detail={"code": "TTS_FAILED", "message": "temporary", "retriable": True},
            worker_id="worker-a",
        )

        retry_response = client.post(f"/jobs/{original_job_id}/retry")

        self.assertEqual(retry_response.status_code, 200)
        retry_job_id = retry_response.json()["id"]
        self.assertEqual(
            services.secret_store.get(retry_job_id, "payload.providers.tts.api_key"),
            "retry-secret-1234",
        )


if __name__ == "__main__":
    unittest.main()
