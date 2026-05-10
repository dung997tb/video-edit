from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TERMINAL_STATUSES = {"done", "failed", "cancelled"}
EVENT_BY_STATUS = {
    "done": "job.completed",
    "failed": "job.failed",
    "cancelled": "job.cancelled",
}


class WebhookRecorder:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.event = threading.Event()


class WebhookServer(ThreadingHTTPServer):
    daemon_threads = True


def start_webhook_server(port: int) -> tuple[WebhookServer, str, WebhookRecorder]:
    recorder = WebhookRecorder()

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

    server = WebhookServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/webhook", recorder


def _headers(api_key: str | None, *, json_body: bool = False) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def request_json(
    method: str,
    base_url: str,
    path: str,
    *,
    api_key: str | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        _url(base_url, path),
        data=data,
        headers=_headers(api_key, json_body=payload is not None),
        method=method,
    )
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise AssertionError(f"{method} {path} failed: {exc}") from exc


def create_job(base_url: str, api_key: str | None, input_uri: str, webhook_url: str) -> dict[str, Any]:
    return request_json(
        "POST",
        base_url,
        "/jobs",
        api_key=api_key,
        payload={
            "pipeline_type": "low_level",
            "input_uri": input_uri,
            "payload": {
                "webhook_url": webhook_url,
                "operations": [
                    {"type": "cut", "params": {"start": 0, "duration": 3}},
                ],
            },
        },
    )


def run(args: argparse.Namespace) -> None:
    started_at = time.perf_counter()
    server, webhook_url, recorder = start_webhook_server(args.webhook_port)
    try:
        print(f"Webhook server: {webhook_url}")
        created = create_job(args.base_url, args.api_key, args.input_uri, webhook_url)
        job_id = created["id"]
        print(f"Created job: {job_id}")

        deadline = time.monotonic() + args.timeout
        final_job: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            job = request_json("GET", args.base_url, f"/jobs/{job_id}", api_key=args.api_key)
            print(f"Job status: {job['status']} progress={job.get('progress')}%")
            if job["status"] in TERMINAL_STATUSES:
                final_job = job
                break
            time.sleep(args.poll_seconds)

        assert final_job is not None, f"job did not finish within {args.timeout}s"
        assert recorder.event.wait(10.0), "job reached terminal state but no webhook POST was received"

        payload = recorder.payloads[0]
        expected_event = EVENT_BY_STATUS[final_job["status"]]
        assert payload["event"] == expected_event, payload
        assert payload["job_id"] == job_id, payload
        assert payload["status"] == final_job["status"], payload
        assert "result_items" in (payload.get("metadata") or {}), payload

        elapsed = time.perf_counter() - started_at
        print("PASSED live webhook test")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"Elapsed: {elapsed:.2f}s")
    finally:
        server.shutdown()
        server.server_close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live webhook end-to-end test for AI Video Engine API.")
    parser.add_argument("--base-url", default="http://localhost:6666")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--webhook-port", type=int, default=9999)
    parser.add_argument("--input-uri", default="https://example.com/short.mp4")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    return parser.parse_args()


def main() -> int:
    try:
        run(parse_args())
    except AssertionError as exc:
        print("FAILED live webhook test", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
