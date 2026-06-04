from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.setup_n8n_workflows import (
    activate_workflow,
    all_custom_node_workflows,
    all_workflows,
    create_workflow,
    deactivate_workflow,
    delete_workflow,
    get_execution,
    list_executions,
    n8n_request,
    workflow_webhook_path,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


TERMINAL = {"done", "failed", "cancelled"}
HELPER_NAME = "WF-HELPER — Webhook Receiver"
BATCH_NAME = "WF-17 — Batch 4 Videos Song Song"
CUSTOM_TRIGGER_NAME = "CN-05 — Trigger Callback"
CUSTOM_CANCEL_NAME = "CN-06 — Cancel Flow"
CUSTOM_GET_LIST_NAME = "CN-07 — Get + List"
CUSTOM_BATCH_NAME = "CN-08 — Batch 4 Jobs"
SMOKE_NAMES = {
    "WF-01 — Cut + Speed + Flip",
    "WF-09 — Audio Extract",
    "WF-15 — Extract Frames",
}
CUSTOM_SMOKE_NAMES = {"CN-01 — Smoke Cut 5s"}
CUSTOM_PRESET_NAMES = {
    "CN-02 — Preset Low Level Cut+Portrait 1080x1920",
    "CN-03 — Preset Dubbing VI",
    "CN-04 — Preset Subtitle Burn",
}


@dataclass
class TestResult:
    id: str
    name: str
    status: str
    seconds: float
    note: str
    job_id: str | None = None
    output_path: str | None = None


class N8nNodeTestRunner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.n8n_url = args.n8n_url.rstrip("/")
        self.n8n_api_key = args.n8n_api_key
        self.video_api_url = args.video_api_url.rstrip("/")
        self.verify_api_url = args.verify_api_url.rstrip("/")
        self.video_api_key = args.video_api_key
        self.mode = args.mode
        self.credential_id = args.credential_id or None
        self.credential_name = args.credential_name
        self.custom_input_uri = args.input_uri or ""
        self.custom_source_key = args.source_key or ""
        self.custom_source_mode = "inputUri" if self.custom_input_uri else "sourceKey"
        self.custom_source_value = self.custom_input_uri or self.custom_source_key
        self.source_seed_job_id: str | None = None
        self.trigger_prefix = f"codex-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.report_dir = ROOT / args.report_dir
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.ffprobe_path = self.resolve_ffprobe()
        self.api_process: subprocess.Popen[str] | None = None
        self.media_server: http.server.ThreadingHTTPServer | None = None
        self.media_thread: threading.Thread | None = None
        self.tunnel_process: subprocess.Popen[str] | None = None
        self.tunnel_url: str | None = None
        self.created_workflows: list[str] = []
        self.results: list[TestResult] = []
        self.custom_node_available = False
        self.helper_workflow_id: str | None = None
        self.helper_webhook_url: str | None = None

    def resolve_ffprobe(self) -> str:
        env_value = os.getenv("FFPROBE_PATH")
        if env_value:
            return env_value
        bundled = ROOT / "tools" / "ffmpeg" / "ffmpeg-8.1-essentials_build" / "bin" / "ffprobe.exe"
        if bundled.exists():
            return str(bundled)
        return "ffprobe"

    def request_json(
        self,
        method: str,
        base_url: str,
        path: str,
        *,
        api_key: str | None = None,
        payload: dict[str, Any] | None = None,
        timeout: float = 30,
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = Request(f"{base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"{method} {path} failed: {exc}") from exc

    def health_ok(self, base_url: str, timeout: float = 3) -> bool:
        try:
            with urlopen(f"{base_url}/health", timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return response.status == 200 and "ok" in raw
        except Exception:
            return False

    def start_api(self) -> None:
        if self.health_ok(self.verify_api_url):
            return
        if not self.args.auto_start_api:
            raise RuntimeError(f"Video API is not reachable at {self.verify_api_url}")
        env = os.environ.copy()
        env.update(
            {
                "API_PORT": self.verify_api_url.rsplit(":", 1)[-1],
                "API_EMBEDDED_WORKER": "true",
                "API_ALLOW_INPUT_PATH": "true",
                "WEBHOOKS_ENABLED": "true",
                "METRICS_ENABLED": "true",
                "FFPROBE_PATH": self.ffprobe_path,
            }
        )
        if self.video_api_key:
            env["API_SECRET_KEY"] = self.video_api_key
            env["API_AUTH_ENABLED"] = "true"
        else:
            env["API_SECRET_KEY"] = "codex-n8n-test-key"
            env["API_AUTH_ENABLED"] = "false"
        self.api_process = subprocess.Popen(
            [sys.executable, "main.py", "api"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if self.api_process.poll() is not None:
                if self.health_ok(self.verify_api_url):
                    self.api_process = None
                    return
                output = self.api_process.stdout.read() if self.api_process.stdout else ""
                raise RuntimeError(f"API exited early:\n{output}")
            if self.health_ok(self.verify_api_url):
                return
            time.sleep(1)
        raise RuntimeError(f"API did not become healthy at {self.verify_api_url}")

    def stop_api(self) -> None:
        if self.api_process is None:
            return
        if self.api_process.poll() is None:
            self.api_process.terminate()
            try:
                self.api_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.api_process.kill()
                self.api_process.wait(timeout=10)
        self.api_process = None

    def start_media_server(self) -> None:
        if self.mode != "custom-node" or self.custom_source_mode != "inputUri" or self.custom_input_uri:
            return
        media_file = ROOT / "test_input.mp4"
        if not media_file.exists():
            raise RuntimeError(f"Missing custom-node test media: {media_file}")
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.bind(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
        self.media_server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.media_thread = threading.Thread(target=self.media_server.serve_forever, name="n8n-custom-media", daemon=True)
        self.media_thread.start()
        self.custom_input_uri = f"http://127.0.0.1:{port}/test_input.mp4"
        self.custom_source_value = self.custom_input_uri

    def stop_media_server(self) -> None:
        if self.media_server is None:
            return
        self.media_server.shutdown()
        self.media_server.server_close()
        if self.media_thread is not None:
            self.media_thread.join(timeout=5)
        self.media_server = None
        self.media_thread = None

    def start_tunnel(self) -> str | None:
        if not self.args.tunnel:
            return None
        port = 6666
        match = re.search(r":(\d+)", self.verify_api_url)
        if match:
            port = int(match.group(1))

        print(f"Starting localtunnel on port {port}...")
        self.tunnel_process = subprocess.Popen(
            ["npx", "-y", "localtunnel", "--port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        deadline = time.monotonic() + 15
        tunnel_url = None
        while time.monotonic() < deadline:
            line = self.tunnel_process.stdout.readline()
            if not line:
                time.sleep(0.5)
                continue
            line_str = line.strip()
            print(f"[localtunnel] {line_str}")
            if "your url is:" in line_str:
                tunnel_url = line_str.split("your url is:", 1)[1].strip()
                break

        if not tunnel_url:
            self.tunnel_process.terminate()
            raise RuntimeError("Failed to obtain tunnel URL from localtunnel")

        print(f"Tunnel successfully created: {tunnel_url}")
        return tunnel_url

    def stop_tunnel(self) -> None:
        if self.tunnel_process is not None:
            print("Stopping localtunnel...")
            self.tunnel_process.terminate()
            try:
                self.tunnel_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.tunnel_process.kill()
            self.tunnel_process = None

    def restart_api(self) -> None:
        if not self.args.auto_start_api:
            return
        self.stop_api()
        self.start_api()

    def detect_custom_node(self) -> None:
        try:
            n8n_request(
                "GET",
                self.n8n_url,
                "/api/v1/credentials/schema/aiVideoEngineApi",
                self.n8n_api_key,
            )
            self.custom_node_available = True
        except RuntimeError:
            self.custom_node_available = False

    def list_credentials(self) -> list[dict[str, Any]]:
        payload = n8n_request("GET", self.n8n_url, "/api/v1/credentials", self.n8n_api_key)
        data = payload.get("data", payload)
        return data if isinstance(data, list) else []

    def create_ai_video_credential(self) -> str:
        auth_type = "apiKey" if self.video_api_key else "apiKey"
        api_key = self.video_api_key or "codex-n8n-test-key"
        payload = {
            "name": self.credential_name,
            "type": "aiVideoEngineApi",
            "data": {
                "baseUrl": self.video_api_url,
                "authType": auth_type,
                "apiKey": api_key,
                "allowedHttpRequestDomains": "all",
            },
        }
        created = n8n_request("POST", self.n8n_url, "/api/v1/credentials", self.n8n_api_key, payload)
        credential_id = created.get("id") or (created.get("data") or {}).get("id")
        if not credential_id:
            raise RuntimeError(f"Credential create response missing id: {created}")
        return str(credential_id)

    def resolve_custom_credential(self) -> None:
        if self.mode != "custom-node":
            return
        if self.credential_id:
            return
        for credential in self.list_credentials():
            if credential.get("type") == "aiVideoEngineApi" and credential.get("name") == self.credential_name:
                self.credential_id = str(credential["id"])
                return
        if not self.args.create_credential:
            raise RuntimeError(
                f'Missing n8n credential "{self.credential_name}" of type aiVideoEngineApi; '
                "pass --credential-id or enable --create-credential"
            )
        self.credential_id = self.create_ai_video_credential()

    def upload_custom_source_key(self) -> None:
        if self.mode != "custom-node" or self.custom_source_value:
            return
        media_file = ROOT / "test_input.mp4"
        if not media_file.exists():
            raise RuntimeError(f"Missing custom-node test media: {media_file}")

        boundary = f"----codex-{uuid.uuid4().hex}"
        payload_json = json.dumps(
            {
                "output_name": f"cn-source-seed-{self.trigger_prefix}",
                "operations": [{"type": "cut", "params": {"start": 0, "duration": 1}}],
            },
            ensure_ascii=False,
        )
        body = bytearray()

        def add_field(name: str, value: str) -> None:
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
            body.extend(value.encode("utf-8"))
            body.extend(b"\r\n")

        add_field("pipeline_type", "low_level")
        add_field("payload_json", payload_json)
        add_field("metadata_json", "{}")
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(b'Content-Disposition: form-data; name="file"; filename="test_input.mp4"\r\n')
        body.extend(b"Content-Type: video/mp4\r\n\r\n")
        body.extend(media_file.read_bytes())
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        headers = {
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        if self.video_api_key:
            headers["X-API-Key"] = self.video_api_key
        req = Request(f"{self.verify_api_url}/jobs/upload", data=bytes(body), headers=headers, method="POST")
        with urlopen(req, timeout=120) as response:
            uploaded = json.loads(response.read().decode("utf-8"))

        source_key = (uploaded.get("payload") or {}).get("source_key") or uploaded.get("source_key")
        if not source_key:
            raise RuntimeError(f"Upload response missing source_key: {uploaded}")
        self.custom_source_key = str(source_key)
        self.custom_source_mode = "sourceKey"
        self.custom_source_value = self.custom_source_key
        self.source_seed_job_id = str(uploaded.get("id") or "")

    def make_report(self) -> dict[str, Any]:
        totals = {"PASS": 0, "FAIL": 0, "SKIP": 0, "BLOCKED": 0}
        for result in self.results:
            totals[result.status] = totals.get(result.status, 0) + 1
        payload = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "n8n_url": self.n8n_url,
            "video_api_url": self.video_api_url,
            "verify_api_url": self.verify_api_url,
            "mode": self.mode,
            "credential_id": self.credential_id,
            "credential_name": self.credential_name if self.mode == "custom-node" else None,
            "source_mode": self.custom_source_mode if self.mode == "custom-node" else None,
            "source_value": self.custom_source_value if self.mode == "custom-node" else None,
            "source_seed_job_id": self.source_seed_job_id,
            "input_uri": self.custom_input_uri if self.mode == "custom-node" else None,
            "custom_node_available": self.custom_node_available,
            "totals": totals,
            "results": [asdict(result) for result in self.results],
        }
        report_json = self.report_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_html = self.report_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        report_html.write_text(self.render_html(payload), encoding="utf-8")
        payload["report_json"] = str(report_json)
        payload["report_html"] = str(report_html)
        return payload

    def render_html(self, payload: dict[str, Any]) -> str:
        rows = []
        for result in payload["results"]:
            rows.append(
                "<tr>"
                f"<td>{result['id']}</td>"
                f"<td>{result['name']}</td>"
                f"<td>{result['status']}</td>"
                f"<td>{result['seconds']:.2f}</td>"
                f"<td>{result['note']}</td>"
                "</tr>"
            )
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>n8n Node Test Report</title>"
            "<style>body{font-family:Segoe UI,Arial,sans-serif;padding:24px}"
            "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px}"
            "th{background:#f4f4f4;text-align:left}.PASS{color:#0a7d24}.FAIL{color:#b00020}"
            ".SKIP,.BLOCKED{color:#8a6d00}</style></head><body>"
            f"<h1>n8n Node Test Report</h1><p>Generated: {payload['timestamp']}</p>"
            f"<p>Mode: {payload['mode']}</p><p>Custom node available: {payload['custom_node_available']}</p>"
            "<table><thead><tr><th>ID</th><th>Name</th><th>Status</th><th>Seconds</th><th>Note</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></body></html>"
        )

    def add_result(
        self,
        test_id: str,
        name: str,
        status: str,
        started_at: float,
        note: str,
        *,
        job_id: str | None = None,
        output_path: str | None = None,
    ) -> None:
        self.results.append(
            TestResult(
                id=test_id,
                name=name,
                status=status,
                seconds=round(time.perf_counter() - started_at, 2),
                note=note,
                job_id=job_id,
                output_path=output_path,
            )
        )

    def ffprobe(self, path: Path) -> dict[str, Any]:
        result = subprocess.run(
            [self.ffprobe_path, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            cwd=ROOT,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ffprobe failed")
        return json.loads(result.stdout)

    def verify_job_output(self, workflow_name: str, final_json: dict[str, Any]) -> str:
        status = final_json.get("status")
        if status != "done":
            raise AssertionError(f"job status={status}")
        if workflow_name == BATCH_NAME:
            statuses = final_json.get("statuses") or []
            if not statuses:
                raise AssertionError("batch statuses empty")
            failed = [item for item in statuses if item.get("status") != "done"]
            if failed:
                raise AssertionError(f"batch failed statuses={failed}")
            return f"batch completed={len(statuses)}"

        output_path = final_json.get("output_path")
        if not output_path:
            raise AssertionError("missing output_path")
        full_path = Path(output_path)
        if not full_path.is_absolute():
            full_path = ROOT / output_path
        if workflow_name == "WF-15 — Extract Frames":
            if not full_path.exists() or not full_path.is_dir():
                raise AssertionError(f"frames folder missing: {full_path}")
            count = len(list(full_path.glob("*.jpg")))
            if count <= 0:
                raise AssertionError("no jpg frames written")
            return f"frames={count}"
        if not full_path.exists() or full_path.stat().st_size <= 0:
            raise AssertionError(f"output missing or empty: {full_path}")
        probe = self.ffprobe(full_path)
        streams = probe.get("streams", [])
        video_streams = [item for item in streams if item.get("codec_type") == "video"]
        audio_streams = [item for item in streams if item.get("codec_type") == "audio"]
        if workflow_name == "WF-09 — Audio Extract":
            if not audio_streams:
                raise AssertionError("audio extract missing audio stream")
            return f"audio_streams={len(audio_streams)}"
        if not video_streams:
            raise AssertionError("output missing video stream")
        if workflow_name == "CN-01 — Smoke Cut 5s":
            duration = float((probe.get("format") or {}).get("duration") or 0)
            if not 3.5 <= duration <= 6.5:
                raise AssertionError(f"unexpected duration={duration:.2f}s")
            return f"duration={duration:.2f}s video={len(video_streams)} audio={len(audio_streams)}"
        if workflow_name == "CN-02 — Preset Low Level Cut+Portrait 1080x1920":
            first_video = video_streams[0]
            width = int(first_video.get("width") or 0)
            height = int(first_video.get("height") or 0)
            if (width, height) != (1080, 1920):
                raise AssertionError(f"unexpected size={width}x{height}")
            return f"size={width}x{height} video={len(video_streams)} audio={len(audio_streams)}"
        if workflow_name == "CN-03 — Preset Dubbing VI" and not audio_streams:
            raise AssertionError("dubbing output missing audio stream")
        return f"video={len(video_streams)} audio={len(audio_streams)}"

    def extract_last_json(self, execution: dict[str, Any]) -> dict[str, Any]:
        run_data = ((execution.get("data") or {}).get("resultData") or {}).get("runData") or {}
        last_node = ((execution.get("data") or {}).get("resultData") or {}).get("lastNodeExecuted")
        if not last_node or last_node not in run_data:
            raise AssertionError("last executed node missing in runData")
        node_runs = run_data[last_node]
        last_run = node_runs[-1]
        items = (((last_run.get("data") or {}).get("main") or [[]])[0] or [])
        if not items:
            raise AssertionError(f"node {last_node} returned no items")
        return items[0].get("json") or {}

    def extract_node_items(self, execution: dict[str, Any], node_name: str) -> list[dict[str, Any]]:
        run_data = ((execution.get("data") or {}).get("resultData") or {}).get("runData") or {}
        if node_name not in run_data:
            raise AssertionError(f"node {node_name} missing in runData")
        node_runs = run_data[node_name]
        last_run = node_runs[-1]
        items = (((last_run.get("data") or {}).get("main") or [[]])[0] or [])
        return [item.get("json") or {} for item in items]

    def extract_node_json(self, execution: dict[str, Any], node_name: str) -> dict[str, Any]:
        items = self.extract_node_items(execution, node_name)
        if not items:
            raise AssertionError(f"node {node_name} returned no items")
        return items[0]

    def create_and_activate(self, workflow: dict[str, Any]) -> str:
        workflow_id = create_workflow(self.n8n_url, self.n8n_api_key, workflow)
        self.created_workflows.append(workflow_id)
        activate_workflow(self.n8n_url, self.n8n_api_key, workflow_id)
        return workflow_id

    def cleanup_workflows(self) -> None:
        if self.args.keep_workflows:
            return
        for workflow_id in reversed(self.created_workflows):
            try:
                deactivate_workflow(self.n8n_url, self.n8n_api_key, workflow_id)
            except Exception:
                pass
            try:
                delete_workflow(self.n8n_url, self.n8n_api_key, workflow_id)
            except Exception:
                pass
        self.created_workflows.clear()

    def wait_for_execution(self, workflow_id: str, *, started_after: float) -> dict[str, Any]:
        deadline = time.monotonic() + 30
        execution_id: str | None = None
        while time.monotonic() < deadline and execution_id is None:
            payload = list_executions(
                self.n8n_url,
                self.n8n_api_key,
                workflow_id=workflow_id,
                limit=10,
            )
            for item in payload.get("data", []):
                execution_started = item.get("startedAt") or item.get("createdAt")
                if execution_started and self.iso_to_ts(execution_started) >= started_after - 1:
                    execution_id = str(item["id"])
                    break
            if execution_id is None:
                time.sleep(1)
        if execution_id is None:
            raise RuntimeError(f"no execution found for workflow {workflow_id}")

        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            execution = get_execution(self.n8n_url, self.n8n_api_key, execution_id, include_data=True)
            if (
                execution.get("finished")
                or execution.get("stoppedAt")
                or execution.get("status") in {"success", "error", "crashed", "canceled", "cancelled"}
            ):
                return execution
            time.sleep(2)
        raise RuntimeError(f"execution {execution_id} timed out")

    def iso_to_ts(self, value: str) -> float:
        fixed = value.replace("Z", "+00:00")
        return datetime.fromisoformat(fixed).timestamp()

    def trigger_workflow(self, workflow: dict[str, Any], workflow_id: str) -> dict[str, Any]:
        trigger_path = workflow_webhook_path(workflow)
        if not trigger_path:
            raise RuntimeError(f"workflow {workflow['name']} has no webhook trigger path")
        started_after = time.time()
        req = Request(
            f"{self.n8n_url}/webhook/{trigger_path}",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=20):
            pass
        return self.wait_for_execution(workflow_id, started_after=started_after)

    def workflows_for_group(self) -> list[dict[str, Any]]:
        if self.mode == "custom-node":
            if not self.credential_id:
                raise RuntimeError("custom-node mode requires a resolved credential id")
            workflows = all_custom_node_workflows(
                self.custom_source_value,
                self.credential_id,
                source_mode=self.custom_source_mode,
                credential_name=self.credential_name,
                trigger_mode="webhook",
                webhook_prefix=self.trigger_prefix,
            )
            selected: list[dict[str, Any]] = []
            for workflow in workflows:
                name = workflow["name"]
                if name == CUSTOM_TRIGGER_NAME:
                    if self.args.group in {"all", "trigger"}:
                        selected.append(workflow)
                    continue
                if name == CUSTOM_BATCH_NAME:
                    if self.args.group in {"all", "batch"}:
                        selected.append(workflow)
                    continue
                if self.args.group == "smoke":
                    if name in CUSTOM_SMOKE_NAMES:
                        selected.append(workflow)
                    continue
                if self.args.group == "preset":
                    if name in CUSTOM_PRESET_NAMES:
                        selected.append(workflow)
                    continue
                if self.args.group == "all":
                    selected.append(workflow)
            return selected

        workflows = all_workflows(
            self.video_api_url,
            self.video_api_key,
            trigger_mode="webhook",
            webhook_prefix=self.trigger_prefix,
        )
        selected: list[dict[str, Any]] = []
        for workflow in workflows:
            name = workflow["name"]
            if name == HELPER_NAME:
                if self.args.group in {"all", "trigger"}:
                    selected.append(workflow)
                continue
            if name == BATCH_NAME:
                if self.args.group == "batch":
                    selected.append(workflow)
                continue
            if self.args.group == "smoke":
                if name in SMOKE_NAMES:
                    selected.append(workflow)
                continue
            if self.args.group in {"all", "preset"}:
                selected.append(workflow)
        return selected

    def is_helper_workflow(self, workflow: dict[str, Any]) -> bool:
        return workflow["name"] in {HELPER_NAME, CUSTOM_TRIGGER_NAME}

    def result_id_for_workflow(self, workflow: dict[str, Any], index: int) -> str:
        if self.mode == "custom-node":
            return workflow["name"].split(" — ", 1)[0]
        return f"W{index:02d}"

    def verify_custom_workflow_execution(self, workflow_name: str, execution: dict[str, Any]) -> tuple[str, str | None, str | None]:
        if workflow_name == CUSTOM_BATCH_NAME:
            wait_items = self.extract_node_items(execution, "Wait Job")
            if len(wait_items) != 4:
                raise AssertionError(f"expected 4 batch outputs, got {len(wait_items)}")
            failed = [item for item in wait_items if item.get("status") != "done"]
            if failed:
                raise AssertionError(f"batch failed statuses={failed}")
            for item in wait_items:
                self.verify_job_output(CUSTOM_BATCH_NAME, item)
            return "batch completed=4", None, None

        if workflow_name == CUSTOM_CANCEL_NAME:
            created = self.extract_node_json(execution, "Create Job")
            job_id = str(created.get("job_id") or created.get("id") or "")
            if not job_id:
                raise AssertionError("cancel flow create response missing job id")
            job = self.wait_job(job_id, timeout_seconds=120)
            if job.get("status") != "cancelled":
                raise AssertionError(f"expected cancelled, got {job.get('status')}")
            return "terminal cancelled", job_id, job.get("output_path")

        if workflow_name == CUSTOM_GET_LIST_NAME:
            got = self.extract_node_json(execution, "Get Job")
            listed = self.extract_node_items(execution, "List Jobs")
            if got.get("status") != "done":
                raise AssertionError(f"get returned status={got.get('status')}")
            if not listed:
                raise AssertionError("list returned no jobs")
            note = self.verify_job_output(workflow_name, got)
            return f"{note}; list_items={len(listed)}", str(got.get("job_id") or got.get("id")), got.get("output_path")

        final_json = self.extract_last_json(execution)
        note = self.verify_job_output(workflow_name, final_json)
        return note, str(final_json.get("job_id") or final_json.get("id") or ""), final_json.get("output_path")

    def run_workflow_cases(self) -> None:
        for index, workflow in enumerate(self.workflows_for_group(), start=1):
            started_at = time.perf_counter()
            if not self.is_helper_workflow(workflow):
                self.restart_api()
            workflow_id = self.create_and_activate(workflow)
            if self.is_helper_workflow(workflow):
                self.helper_workflow_id = workflow_id
                trigger_path = workflow_webhook_path(workflow)
                self.helper_webhook_url = f"{self.n8n_url}/webhook/{trigger_path}"
                if self.mode != "custom-node":
                    self.add_result(
                        f"W{index:02d}",
                        workflow["name"],
                        "PASS",
                        started_at,
                        f"helper ready at {trigger_path}",
                    )
                continue
            try:
                execution = self.trigger_workflow(workflow, workflow_id)
                if self.mode == "custom-node":
                    note, job_id, output_path = self.verify_custom_workflow_execution(workflow["name"], execution)
                    self.add_result(
                        self.result_id_for_workflow(workflow, index),
                        workflow["name"],
                        "PASS",
                        started_at,
                        note,
                        job_id=job_id,
                        output_path=output_path,
                    )
                    continue
                created_job = self.extract_last_json(execution)
                job_id = created_job.get("id") or created_job.get("job_id")
                if not job_id:
                    raise AssertionError("create response missing job id")
                final_job = self.wait_job(str(job_id), timeout_seconds=900)
                note = self.verify_job_output(workflow["name"], final_job)
                self.add_result(
                    f"W{index:02d}",
                    workflow["name"],
                    "PASS",
                    started_at,
                    note,
                    job_id=str(job_id),
                    output_path=final_job.get("output_path"),
                )
            except Exception as exc:
                self.add_result(self.result_id_for_workflow(workflow, index), workflow["name"], "FAIL", started_at, str(exc))

    def wait_job(self, job_id: str, timeout_seconds: int = 300) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            job = self.request_json("GET", self.verify_api_url, f"/jobs/{job_id}", api_key=self.video_api_key or None)
            if job.get("status") in TERMINAL:
                return job
            time.sleep(1)
        raise RuntimeError(f"job {job_id} did not finish within {timeout_seconds}s")

    def helper_execution_after(self, since_ts: float, *, timeout_seconds: int = 60) -> dict[str, Any]:
        if not self.helper_workflow_id:
            raise RuntimeError("helper workflow not created")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            payload = list_executions(
                self.n8n_url,
                self.n8n_api_key,
                workflow_id=self.helper_workflow_id,
                limit=10,
            )
            for item in payload.get("data", []):
                execution_started = item.get("startedAt") or item.get("createdAt")
                if execution_started and self.iso_to_ts(execution_started) >= since_ts - 1:
                    return get_execution(self.n8n_url, self.n8n_api_key, item["id"], include_data=True)
            time.sleep(1)
        raise RuntimeError("helper execution not received")

    def run_trigger_cases(self) -> None:
        if self.args.group not in {"all", "trigger"}:
            return
        if not self.helper_webhook_url:
            self.results.append(
                TestResult("T-TR", "Webhook callback tests", "SKIP", 0.0, "helper workflow not available")
            )
            return
        if self.mode == "custom-node":
            self.run_trigger_completed("CN-05", CUSTOM_TRIGGER_NAME)
            return
        self.run_trigger_completed()
        self.run_trigger_failed()
        self.run_trigger_cancelled()

    def run_trigger_completed(self, test_id: str = "T-TR1", name: str = "Trigger completed") -> None:
        started_at = time.perf_counter()
        try:
            self.restart_api()
            since = time.time()
            created = self.request_json(
                "POST",
                self.verify_api_url,
                "/jobs",
                api_key=self.video_api_key or None,
                payload={
                    "pipeline_type": "low_level",
                    "input_path": "test_input.mp4",
                    "payload": {
                        "webhook_url": self.helper_webhook_url,
                        "output_name": f"callback-done-{self.trigger_prefix}",
                        "operations": [{"type": "cut", "params": {"start": 0, "duration": 4}}],
                    },
                },
            )
            job = self.wait_job(created["id"], timeout_seconds=240)
            execution = self.helper_execution_after(since)
            output = self.extract_last_json(execution)
            if output.get("event") != "job.completed":
                raise AssertionError(f"unexpected event {output}")
            self.add_result(
                test_id,
                name,
                "PASS",
                started_at,
                "received job.completed",
                job_id=job.get("id"),
                output_path=job.get("output_path"),
            )
        except Exception as exc:
            self.add_result(test_id, name, "FAIL", started_at, str(exc))

    def run_trigger_failed(self) -> None:
        started_at = time.perf_counter()
        try:
            self.restart_api()
            since = time.time()
            created = self.request_json(
                "POST",
                self.verify_api_url,
                "/jobs",
                api_key=self.video_api_key or None,
                payload={
                    "pipeline_type": "low_level",
                    "input_path": "test_input.mp4",
                    "payload": {
                        "webhook_url": self.helper_webhook_url,
                        "operations": [{"type": "unknown_op", "params": {}}],
                    },
                },
            )
            execution = self.helper_execution_after(since, timeout_seconds=25)
            output = self.extract_last_json(execution)
            if output.get("event") != "job.failed":
                raise AssertionError(f"unexpected event {output}")
            self.add_result("T-TR2", "Trigger failed", "PASS", started_at, "received job.failed", job_id=created["id"])
        except Exception as exc:
            self.add_result("T-TR2", "Trigger failed", "FAIL", started_at, str(exc))

    def run_trigger_cancelled(self) -> None:
        started_at = time.perf_counter()
        try:
            self.restart_api()
            since = time.time()
            created = self.request_json(
                "POST",
                self.verify_api_url,
                "/jobs",
                api_key=self.video_api_key or None,
                payload={
                    "pipeline_type": "low_level",
                    "input_path": "test.mp4",
                    "payload": {
                        "webhook_url": self.helper_webhook_url,
                        "output_name": f"cancel-{self.trigger_prefix}",
                        "operations": [
                            {
                                "type": "blur_bg_portrait",
                                "params": {"output_width": 1080, "output_height": 1920},
                            },
                            {"type": "auto_zoom", "params": {"interval_seconds": 5}},
                            {"type": "pad_border", "params": {"size": 10, "color": "#000000"}},
                        ],
                    },
                },
            )
            time.sleep(1)
            self.request_json(
                "POST",
                self.verify_api_url,
                f"/jobs/{created['id']}/cancel",
                api_key=self.video_api_key or None,
                payload={},
            )
            execution = self.helper_execution_after(since, timeout_seconds=45)
            output = self.extract_last_json(execution)
            if output.get("event") != "job.cancelled":
                raise AssertionError(f"unexpected event {output}")
            self.add_result("T-TR3", "Trigger cancelled", "PASS", started_at, "received job.cancelled", job_id=created["id"])
        except Exception as exc:
            self.add_result("T-TR3", "Trigger cancelled", "FAIL", started_at, str(exc))

    def run(self) -> dict[str, Any]:
        self.detect_custom_node()
        if self.mode == "custom-node" and not self.custom_node_available:
            self.add_result("SETUP", "Custom node availability", "BLOCKED", time.perf_counter(), "aiVideoEngineApi schema not loaded in n8n")
            return self.make_report()
        self.start_api()
        if self.args.tunnel:
            tunnel_url = self.start_tunnel()
            if tunnel_url:
                self.tunnel_url = tunnel_url
                self.video_api_url = tunnel_url.rstrip("/")
        self.start_media_server()
        self.upload_custom_source_key()
        self.resolve_custom_credential()
        self.run_workflow_cases()
        self.run_trigger_cases()
        self.cleanup_workflows()
        report = self.make_report()
        self.stop_media_server()
        self.stop_tunnel()
        self.stop_api()
        return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run automated n8n workflow tests for AI Video Engine.")
    parser.add_argument("--n8n-url", default="http://127.0.0.1:5678")
    parser.add_argument("--n8n-api-key", required=True)
    parser.add_argument("--video-api-url", default="http://host.docker.internal:6666")
    parser.add_argument("--verify-api-url", default="http://127.0.0.1:6666")
    parser.add_argument("--video-api-key", default="")
    parser.add_argument("--mode", choices=("http-request", "custom-node"), default="http-request")
    parser.add_argument("--credential-id", default="")
    parser.add_argument("--credential-name", default="AI Video Engine API")
    parser.add_argument("--create-credential", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--input-uri", default="", help="Existing media URL for custom-node mode")
    parser.add_argument("--source-key", default="", help="Existing artifact source_key for custom-node mode")
    parser.add_argument("--group", choices=("all", "smoke", "preset", "trigger", "batch"), default="smoke")
    parser.add_argument("--auto-start-api", action="store_true")
    parser.add_argument("--tunnel", action="store_true", help="Start localtunnel for public URL callback")
    parser.add_argument("--keep-workflows", action="store_true")
    parser.add_argument("--report-dir", default="test_runs/n8n_node_tests")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runner = N8nNodeTestRunner(args)
    try:
        report = runner.run()
    finally:
        runner.cleanup_workflows()
        runner.stop_media_server()
        runner.stop_tunnel()
        runner.stop_api()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
