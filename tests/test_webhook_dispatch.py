from __future__ import annotations

import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import patch

from core.job_manager import InMemoryJobRepository, JobManager


class _WebhookRecorder:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.event = threading.Event()


class _WebhookHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


def _start_webhook_server(delay_seconds: float = 0.0) -> tuple[_WebhookHTTPServer, str, _WebhookRecorder]:
    recorder = _WebhookRecorder()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length)
            if delay_seconds:
                time.sleep(delay_seconds)
            recorder.requests.append(
                {
                    "path": self.path,
                    "headers": dict(self.headers),
                    "json": json.loads(body.decode("utf-8")),
                }
            )
            recorder.event.set()
            try:
                self.send_response(204)
                self.end_headers()
            except OSError:
                pass

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = _WebhookHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}/webhook", recorder


def _manager() -> JobManager:
    manager = JobManager(InMemoryJobRepository())
    manager.webhooks_enabled = True
    manager.webhook_timeout_seconds = 1.0
    return manager


class WebhookDispatchTests(unittest.TestCase):
    def test_webhook_called_on_complete(self) -> None:
        server, url, recorder = _start_webhook_server()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        manager = _manager()
        job = manager.create_job(pipeline_type="dubbing", source_sha256="hash", metadata={"webhook_url": url})

        manager.complete_job(job.id, "output.mp4")

        self.assertTrue(recorder.event.wait(2.0))
        payload = recorder.requests[0]["json"]
        self.assertEqual(payload["event"], "job.completed")
        self.assertEqual(payload["job_id"], job.id)
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["output_path"], "output.mp4")

    def test_webhook_called_on_fail(self) -> None:
        server, url, recorder = _start_webhook_server()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        manager = _manager()
        job = manager.create_job(pipeline_type="dubbing", source_sha256="hash", metadata={"webhook_url": url})

        manager.fail_job(
            job.id,
            "boom",
            error_detail={"code": "FFMPEG_FAILED", "message": "ffmpeg failed", "step": "render"},
        )

        self.assertTrue(recorder.event.wait(2.0))
        payload = recorder.requests[0]["json"]
        self.assertEqual(payload["event"], "job.failed")
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"], "boom")
        self.assertEqual(payload["error_detail"]["code"], "FFMPEG_FAILED")

    def test_webhook_called_on_cancel(self) -> None:
        server, url, recorder = _start_webhook_server()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        manager = _manager()
        job = manager.create_job(pipeline_type="dubbing", source_sha256="hash", metadata={"webhook_url": url})

        manager.fail_job(job.id, "cancelled by user", cancelled=True)

        self.assertTrue(recorder.event.wait(2.0))
        payload = recorder.requests[0]["json"]
        self.assertEqual(payload["event"], "job.cancelled")
        self.assertEqual(payload["status"], "cancelled")

    def test_webhook_skipped_when_no_url(self) -> None:
        manager = _manager()
        job = manager.create_job(pipeline_type="dubbing", source_sha256="hash")

        with patch("core.job_manager._dispatch_webhook") as dispatch:
            manager.complete_job(job.id, "output.mp4")

        dispatch.assert_not_called()

    def test_webhook_skipped_when_disabled(self) -> None:
        manager = _manager()
        manager.webhooks_enabled = False
        job = manager.create_job(
            pipeline_type="dubbing",
            source_sha256="hash",
            metadata={"webhook_url": "http://127.0.0.1:1/webhook"},
        )

        with patch("core.job_manager._dispatch_webhook") as dispatch:
            manager.complete_job(job.id, "output.mp4")

        dispatch.assert_not_called()

    def test_webhook_payload_schema(self) -> None:
        server, url, recorder = _start_webhook_server()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        manager = _manager()
        job = manager.create_job(
            pipeline_type="dubbing",
            source_sha256="hash",
            metadata={"webhook_url": url, "result_items": [{"kind": "video", "uri": "output.mp4"}]},
        )

        manager.complete_job(job.id, "output.mp4")

        self.assertTrue(recorder.event.wait(2.0))
        payload = recorder.requests[0]["json"]
        self.assertEqual(
            set(payload),
            {"event", "job_id", "status", "output_path", "metadata", "error", "error_detail"},
        )
        self.assertEqual(payload["metadata"]["result_items"][0]["uri"], "output.mp4")
        self.assertIsNone(payload["error"])
        self.assertIsNone(payload["error_detail"])

    def test_webhook_url_from_metadata(self) -> None:
        server, url, recorder = _start_webhook_server()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        manager = _manager()
        job = manager.create_job(pipeline_type="dubbing", source_sha256="hash", metadata={"webhook_url": url})

        manager.complete_job(job.id, "output.mp4")

        self.assertTrue(recorder.event.wait(2.0))
        self.assertEqual(recorder.requests[0]["json"]["job_id"], job.id)

    def test_webhook_url_from_payload(self) -> None:
        server, url, recorder = _start_webhook_server()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        manager = _manager()
        job = manager.create_job(pipeline_type="dubbing", source_sha256="hash", payload={"webhook_url": url})

        manager.complete_job(job.id, "output.mp4")

        self.assertTrue(recorder.event.wait(2.0))
        self.assertEqual(recorder.requests[0]["json"]["event"], "job.completed")

    def test_webhook_timeout_nonblocking(self) -> None:
        server, url, _recorder = _start_webhook_server(delay_seconds=0.5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        manager = _manager()
        manager.webhook_timeout_seconds = 0.05
        job = manager.create_job(pipeline_type="dubbing", source_sha256="hash", metadata={"webhook_url": url})

        started_at = time.perf_counter()
        manager.complete_job(job.id, "output.mp4")
        elapsed = time.perf_counter() - started_at

        self.assertLess(elapsed, 0.2)


if __name__ == "__main__":
    unittest.main()
