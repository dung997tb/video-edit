from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    TestClient = None

from api.main import create_app
from core.secrets import InMemorySecretStore
from tests.helpers import make_services, make_test_root


class _WebhookRecorder:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.event = threading.Event()


class _WebhookHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


def _start_webhook_server() -> tuple[_WebhookHTTPServer, str, _WebhookRecorder]:
    recorder = _WebhookRecorder()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length)
            recorder.payloads.append(json.loads(body.decode("utf-8")))
            recorder.event.set()
            self.send_response(204)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = _WebhookHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}/webhook", recorder


@unittest.skipIf(TestClient is None, "fastapi stack is not installed")
class N8nPayloadCompatTests(unittest.TestCase):
    def _client_and_services(self):
        services = make_services(make_test_root("n8n-payload"))
        services.settings.api_auth_enabled = False
        services.settings.api_embedded_worker = False
        services.settings.api_allow_client_source_sha256 = False
        services.settings.api_rate_limit_per_minute = 0
        services.settings.api_allowed_input_uri_schemes = "http,https"
        services.secret_store = InMemorySecretStore()
        services.pipeline_builders = {
            "low_level": lambda *_args, **_kwargs: None,
            "dubbing": lambda *_args, **_kwargs: None,
            "multilang_dubbing": lambda *_args, **_kwargs: None,
            "split_video": lambda *_args, **_kwargs: None,
        }
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

    def test_n8n_low_level_full_schema(self) -> None:
        client, services = self._client_and_services()

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "low_level",
                "input_uri": "https://example.com/video.mp4",
                "payload": {
                    "request": "cut the first scene",
                    "time_range": {"start": 2, "duration": 3},
                    "operations": [{"id": "cut-main", "type": "cut", "params": {}}],
                    "providers": {"tts": {"provider": "elevenlabs", "api_key": "tts-secret-1234"}},
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        job = services.job_manager.get_job(response.json()["id"])
        self.assertIsNotNone(job)
        operation = job.payload["operations"][0]
        self.assertEqual(operation["name"], "cut")
        self.assertEqual(operation["operation_id"], "cut-main")
        self.assertEqual(operation["start"], 2.0)
        self.assertEqual(operation["duration"], 3.0)
        self.assertEqual(operation["end"], 5.0)
        self.assertEqual(job.payload["providers"]["tts"]["api_key"], "***1234")
        self.assertEqual(services.secret_store.get(job.id, "payload.providers.tts.api_key"), "tts-secret-1234")

    def test_n8n_dubbing_payload(self) -> None:
        client, services = self._client_and_services()

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "dubbing",
                "input_uri": "https://example.com/video.mp4",
                "payload": {
                    "target_language": "vi",
                    "tts_voice": "vi-VN-HoaiMyNeural",
                    "webhook_url": "https://n8n.example/webhook/video",
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        job = services.job_manager.get_job(response.json()["id"])
        self.assertEqual(job.payload["target_language"], "vi")
        self.assertEqual(job.payload["webhook_url"], "https://n8n.example/webhook/video")

    def test_n8n_multilang_dubbing(self) -> None:
        client, services = self._client_and_services()

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "multilang_dubbing",
                "input_uri": "https://example.com/video.mp4",
                "payload": {"target_languages": ["en", "ja", "ko"]},
            },
        )

        self.assertEqual(response.status_code, 200)
        job = services.job_manager.get_job(response.json()["id"])
        self.assertEqual(job.payload["target_languages"], ["en", "ja", "ko"])

    def test_n8n_split_video_direct_pipeline_payload(self) -> None:
        client, services = self._client_and_services()

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "split_video",
                "input_uri": "https://example.com/video.mp4",
                "payload": {"segment_seconds": 30, "start": 5, "end": 65},
            },
        )

        self.assertEqual(response.status_code, 200)
        job = services.job_manager.get_job(response.json()["id"])
        self.assertEqual(job.pipeline_type, "split_video")
        self.assertEqual(job.payload["segment_seconds"], 30)
        self.assertNotIn("operations", job.payload)

    def test_n8n_source_key_flow(self) -> None:
        client, services = self._client_and_services()
        services.artifact_store.upload_bytes("imports/source.mp4", b"source bytes")

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "low_level",
                "source_key": "imports/source.mp4",
                "payload": {"operations": [{"type": "cut", "params": {"duration": 1}}]},
            },
        )

        self.assertEqual(response.status_code, 200)
        job = services.job_manager.get_job(response.json()["id"])
        self.assertEqual(job.payload["source_key"], "imports/source.mp4")

    def test_n8n_provider_key_multi(self) -> None:
        client, services = self._client_and_services()

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "low_level",
                "input_uri": "https://example.com/video.mp4",
                "payload": {
                    "operations": [{"type": "cut", "params": {"duration": 1}}],
                    "providers": {
                        "tts": {"provider": "openai", "api_key": "tts-key-9999"},
                        "translation": {"provider": "deepl", "api_key": "deepl-key-7777"},
                    },
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        job = services.job_manager.get_job(response.json()["id"])
        self.assertEqual(job.payload["providers"]["tts"]["api_key"], "***9999")
        self.assertEqual(job.payload["providers"]["translation"]["api_key"], "***7777")
        self.assertEqual(services.secret_store.get(job.id, "payload.providers.tts.api_key"), "tts-key-9999")
        self.assertEqual(
            services.secret_store.get(job.id, "payload.providers.translation.api_key"),
            "deepl-key-7777",
        )

    def test_n8n_webhook_url_triggers_dispatch(self) -> None:
        client, services = self._client_and_services()
        services.settings.api_allow_private_network_urls = True
        server, url, recorder = _start_webhook_server()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        response = client.post(
            "/jobs",
            json={
                "pipeline_type": "dubbing",
                "input_uri": "https://example.com/video.mp4",
                "payload": {"target_language": "vi", "webhook_url": url},
            },
        )

        self.assertEqual(response.status_code, 200)
        job_id = response.json()["id"]
        services.job_manager.claim_jobs("worker-a", limit=1, lease_seconds=30)
        services.job_manager.complete_job(
            job_id,
            "output.mp4",
            metadata={"result_items": []},
            worker_id="worker-a",
        )

        self.assertTrue(recorder.event.wait(2.0))
        self.assertEqual(recorder.payloads[0]["event"], "job.completed")
        self.assertEqual(recorder.payloads[0]["job_id"], job_id)


if __name__ == "__main__":
    unittest.main()
