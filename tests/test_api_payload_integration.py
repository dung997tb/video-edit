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


if __name__ == "__main__":
    unittest.main()
