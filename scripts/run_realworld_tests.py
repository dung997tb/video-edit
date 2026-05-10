from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TERMINAL_STATUSES = {"done", "failed", "cancelled"}


class WebhookCapture:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.event = threading.Event()


class WebhookServer(ThreadingHTTPServer):
    daemon_threads = True


class StaticFileServer(ThreadingHTTPServer):
    daemon_threads = True


class RealWorldRunner:
    def __init__(self, *, base_url: str, api_key: str, log_dir: Path, timestamp: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timestamp = timestamp
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"realworld_test_{timestamp}.log"
        self.results_path = log_dir / f"realworld_test_{timestamp}.results.json"
        self.status_path = log_dir / f"realworld_test_{timestamp}.status.json"
        self.log_handle = self.log_path.open("a", encoding="utf-8", errors="replace", buffering=1)
        self.results: dict[str, dict[str, Any]] = {}
        self.api_process: subprocess.Popen | None = None
        self.ffprobe_path = self.resolve_tool_path("FFPROBE_PATH", "ffprobe_path", "ffprobe")
        self.rate_limit_per_minute = int(os.getenv("REALWORLD_API_RATE_LIMIT_PER_MINUTE", "200"))

    def close(self) -> None:
        self.stop_api()
        self.log_handle.close()

    def log(self, message: str) -> None:
        line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
        print(line, flush=True)
        self.log_handle.write(line + "\n")
        self.log_handle.flush()

    def resolve_tool_path(self, env_var: str, setting_name: str, fallback: str) -> str:
        value = os.getenv(env_var)
        if value:
            return value
        try:
            from config import settings

            configured = getattr(settings, setting_name, None)
            if configured:
                return str(configured)
        except Exception:
            return fallback
        return fallback

    def error_section(self, test_id: str, message: str) -> None:
        self.log(f"### ERROR SECTION START {test_id}")
        for line in str(message).splitlines() or [""]:
            self.log(line)
        self.log(f"### ERROR SECTION END {test_id}")

    def set_result(self, test_id: str, status: str, elapsed: float, note: str) -> None:
        self.results[test_id] = {
            "status": status,
            "seconds": round(elapsed, 2),
            "note": note,
        }
        self.write_status()
        marker = "PASS" if status == "PASS" else "ERROR" if status == "FAIL" else status
        self.log(f"[{marker}] {test_id} {status} {elapsed:.2f}s - {note}")

    def write_status(self) -> None:
        payload = {
            "timestamp": self.timestamp,
            "log_path": str(self.log_path),
            "results_path": str(self.results_path),
            "results": self.results,
        }
        self.status_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        self.results_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def run_command(
        self,
        test_id: str,
        args: list[str],
        *,
        timeout: float,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, float]:
        start = time.perf_counter()
        self.log(f"### START {test_id}: {subprocess.list2cmdline(args)}")
        process = subprocess.Popen(
            args,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        lines: list[str] = []
        timed_out = False
        while True:
            if process.stdout is not None:
                line = process.stdout.readline()
                if line:
                    line = line.rstrip("\n")
                    lines.append(line)
                    self.log(f"{test_id}> {line}")
            if process.poll() is not None:
                if process.stdout is not None:
                    for line in process.stdout.read().splitlines():
                        lines.append(line)
                        self.log(f"{test_id}> {line}")
                break
            if time.perf_counter() - start > timeout:
                timed_out = True
                process.kill()
                break
            time.sleep(0.05)
        rc = process.wait()
        elapsed = time.perf_counter() - start
        if timed_out:
            rc = 124
            self.error_section(test_id, f"Command timed out after {timeout}s")
        if rc != 0:
            self.error_section(test_id, f"Command exited with code {rc}")
        self.log(f"### END {test_id}: rc={rc} elapsed={elapsed:.2f}s")
        return rc, "\n".join(lines), elapsed

    def ffprobe(self, path: str | Path) -> dict[str, Any]:
        result = subprocess.run(
            [
                self.ffprobe_path,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ffprobe failed")
        return json.loads(result.stdout)

    def parse_output_path(self, output: str) -> Path | None:
        for line in reversed([item.strip() for item in output.splitlines() if item.strip()]):
            candidate = Path(line)
            if not candidate.is_absolute():
                candidate = ROOT / candidate
            if candidate.exists():
                return candidate
        return None

    def verify_video(
        self,
        path: Path,
        *,
        width: int | None = None,
        height: int | None = None,
        require_audio: bool = False,
    ) -> str:
        if not path.exists() or path.stat().st_size <= 0:
            raise AssertionError(f"output missing or empty: {path}")
        probe = self.ffprobe(path)
        video_streams = [item for item in probe.get("streams", []) if item.get("codec_type") == "video"]
        audio_streams = [item for item in probe.get("streams", []) if item.get("codec_type") == "audio"]
        if width is not None or height is not None:
            if not video_streams:
                raise AssertionError("no video stream")
            actual = (int(video_streams[0].get("width", 0)), int(video_streams[0].get("height", 0)))
            expected = (width, height)
            if actual != expected:
                raise AssertionError(f"resolution mismatch: expected {expected}, got {actual}")
        if require_audio and not audio_streams:
            raise AssertionError("no audio stream")
        duration = float(probe.get("format", {}).get("duration") or 0)
        return f"{path.relative_to(ROOT)} duration={duration:.2f}s video={len(video_streams)} audio={len(audio_streams)}"

    def verify_audio_file(self, path: Path) -> str:
        if not path.exists() or path.stat().st_size <= 0:
            raise AssertionError(f"audio output missing or empty: {path}")
        probe = self.ffprobe(path)
        audio_streams = [item for item in probe.get("streams", []) if item.get("codec_type") == "audio"]
        if not audio_streams:
            raise AssertionError("no audio stream")
        duration = float(probe.get("format", {}).get("duration") or 0)
        return f"{path.relative_to(ROOT)} duration={duration:.2f}s audio={len(audio_streams)}"

    def run_cli(self, test_id: str, args: list[str], verifier, *, timeout: float = 300) -> None:
        rc, output, elapsed = self.run_command(test_id, [sys.executable, *args], timeout=timeout)
        if rc != 0:
            self.set_result(test_id, "FAIL", elapsed, "CLI command failed; see ERROR SECTION in log")
            return
        try:
            output_path = self.parse_output_path(output)
            if output_path is None:
                raise AssertionError("could not find output path in command output")
            note = verifier(output_path)
            self.set_result(test_id, "PASS", elapsed, note)
        except Exception as exc:
            self.error_section(test_id, str(exc))
            self.set_result(test_id, "FAIL", elapsed, str(exc))

    def auth_headers(self, *, json_body: bool = False) -> dict[str, str]:
        headers = {"Accept": "application/json", "X-API-Key": self.api_key}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 30,
        auth: bool = True,
    ) -> tuple[int, dict[str, Any] | str]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = self.auth_headers(json_body=payload is not None) if auth else {"Accept": "application/json"}
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                try:
                    return response.status, json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    return response.status, raw
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                return exc.code, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return exc.code, raw
        except URLError as exc:
            raise RuntimeError(str(exc)) from exc

    def upload_job(
        self,
        file_path: Path,
        *,
        pipeline_type: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        timeout: float = 60,
    ) -> tuple[int, dict[str, Any] | str]:
        boundary = f"----realworld-{uuid.uuid4().hex}"
        chunks: list[bytes] = []

        def add_field(name: str, value: str) -> None:
            chunks.append(f"--{boundary}\r\n".encode())
            chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            chunks.append(value.encode("utf-8"))
            chunks.append(b"\r\n")

        add_field("pipeline_type", pipeline_type)
        add_field("payload_json", json.dumps(payload))
        add_field("metadata_json", json.dumps(metadata or {}))
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
            "Content-Type: video/mp4\r\n\r\n".encode()
        )
        chunks.append(file_path.read_bytes())
        chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        body = b"".join(chunks)
        request = Request(
            f"{self.base_url}/jobs/upload",
            data=body,
            headers={
                "X-API-Key": self.api_key,
                "Accept": "application/json",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return response.status, json.loads(raw)
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, raw

    def wait_job(self, job_id: str, *, timeout: float = 180) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last_status = None
        while time.monotonic() < deadline:
            status_code, payload = self.request_json("GET", f"/jobs/{job_id}", timeout=20)
            if status_code != 200 or not isinstance(payload, dict):
                raise RuntimeError(f"GET job failed: HTTP {status_code} {payload}")
            status = str(payload.get("status"))
            if status != last_status:
                self.log(f"job {job_id} status={status} progress={payload.get('progress')}")
                last_status = status
            if status in TERMINAL_STATUSES:
                return payload
            time.sleep(1)
        raise TimeoutError(f"job {job_id} did not finish within {timeout}s")

    def start_sse_thread(self, job_id: str) -> tuple[threading.Thread, list[str]]:
        events: list[str] = []

        def worker() -> None:
            request = Request(f"{self.base_url}/jobs/{job_id}/stream", headers=self.auth_headers(), method="GET")
            try:
                with urlopen(request, timeout=180) as response:
                    for raw_line in response:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if line:
                            events.append(line)
                            self.log(f"SSE {job_id}> {line}")
            except Exception as exc:
                events.append(f"ERROR: {exc}")
                self.error_section("T2.3", f"SSE error for {job_id}: {exc}")

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread, events

    def start_api(self) -> bool:
        self.log("### START API server")
        try:
            status, payload = self.request_json("GET", "/health", auth=False, timeout=1)
            self.error_section(
                "API",
                f"{self.base_url} is already responding before runner startup: HTTP {status} {payload}",
            )
            return False
        except Exception:
            pass
        env = os.environ.copy()
        env.update(
            {
                "API_SECRET_KEY": self.api_key,
                "API_AUTH_ENABLED": "true",
                "API_EMBEDDED_WORKER": "true",
                "API_ALLOW_INPUT_PATH": "true",
                "API_PORT": self.base_url.rsplit(":", 1)[-1],
                "API_RATE_LIMIT_PER_MINUTE": str(self.rate_limit_per_minute),
                "WORKER_POLL_INTERVAL_SECONDS": "2",
                "WORKER_POLL_MIN_SECONDS": "2",
                "WORKER_POLL_MAX_SECONDS": "2",
                "WEBHOOKS_ENABLED": "true",
                "METRICS_ENABLED": "true",
            }
        )
        self.api_process = subprocess.Popen(
            [sys.executable, "main.py", "api"],
            cwd=ROOT,
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
            env=env,
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if self.api_process.poll() is not None:
                self.error_section("API", f"API exited early with code {self.api_process.returncode}")
                return False
            try:
                status, payload = self.request_json("GET", "/health", auth=False, timeout=2)
                if status == 200 and isinstance(payload, dict) and payload.get("status") == "ok":
                    time.sleep(0.5)
                    if self.api_process.poll() is not None:
                        self.error_section("API", f"API exited early with code {self.api_process.returncode}")
                        return False
                    self.log("API health ok")
                    return True
            except Exception:
                time.sleep(1)
        self.error_section("API", "API did not become healthy within 45s")
        return False

    def stop_api(self) -> None:
        if self.api_process is None:
            return
        if self.api_process.poll() is None:
            self.log("### STOP API server")
            self.api_process.terminate()
            try:
                self.api_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.api_process.kill()
                self.api_process.wait(timeout=10)
        self.api_process = None

    def start_webhook_server(self, test_id: str, port: int = 0) -> tuple[WebhookServer, str, WebhookCapture]:
        capture = WebhookCapture()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length)
                try:
                    payload = json.loads(body.decode("utf-8"))
                except json.JSONDecodeError:
                    payload = {"raw": body.decode("utf-8", errors="replace")}
                capture.payloads.append(payload)
                capture.event.set()
                self.send_response(204)
                self.end_headers()

            def log_message(self, format: str, *args: Any) -> None:
                return

        server = WebhookServer(("127.0.0.1", port), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_address[1]}/webhook"
        self.log(f"{test_id} webhook listener: {url}")
        return server, url, capture

    def start_static_file_server(self, test_id: str, file_path: Path, port: int = 0) -> tuple[StaticFileServer, str]:
        source = file_path.resolve()
        if not source.exists():
            raise FileNotFoundError(f"static test source not found: {source}")

        class Handler(BaseHTTPRequestHandler):
            def do_HEAD(self) -> None:  # noqa: N802
                self._send_file(send_body=False)

            def do_GET(self) -> None:  # noqa: N802
                self._send_file(send_body=True)

            def _send_file(self, *, send_body: bool) -> None:
                size = source.stat().st_size
                start = 0
                end = size - 1
                status = 200
                range_header = self.headers.get("Range")
                if range_header and range_header.startswith("bytes="):
                    raw_range = range_header.split("=", 1)[1].split(",", 1)[0].strip()
                    raw_start, _, raw_end = raw_range.partition("-")
                    if raw_start:
                        start = int(raw_start)
                    if raw_end:
                        end = int(raw_end)
                    end = min(end, size - 1)
                    status = 206
                content_length = max(end - start + 1, 0)
                self.send_response(status)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(content_length))
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                if not send_body:
                    return
                with source.open("rb") as handle:
                    handle.seek(start)
                    remaining = content_length
                    while remaining > 0:
                        chunk = handle.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)

            def log_message(self, format: str, *args: Any) -> None:
                return

        server = StaticFileServer(("127.0.0.1", port), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_address[1]}/{source.name}"
        self.log(f"{test_id} static file server: {url}")
        return server, url

    def run_phase1(self) -> None:
        self.run_cli(
            "T1.1",
            ["main.py", "run", "test_input.mp4", "--config-file", "pipelines/examples/low_level_basic.json"],
            lambda path: self.verify_video(path),
            timeout=300,
        )
        self.run_cli(
            "T1.2",
            ["main.py", "run", "test_input.mp4", "--config-file", "pipelines/examples/test_suite_portrait.json"],
            lambda path: self.verify_video(path, width=1080, height=1920),
            timeout=420,
        )
        self.run_cli(
            "T1.3",
            ["main.py", "run", "test_input.mp4", "--config-file", "pipelines/examples/test_suite_audio.json"],
            lambda path: self.verify_video(path, require_audio=True),
            timeout=300,
        )
        self.run_cli(
            "T1.4",
            ["main.py", "run", "test.mp4", "--config-file", "pipelines/examples/hstack_test.json"],
            lambda path: self.verify_video(path, width=1280, height=720),
            timeout=300,
        )
        self.run_cli(
            "T1.5",
            ["main.py", "run", "test.mp4", "--config-file", "pipelines/examples/split_screen_tiktok.json"],
            lambda path: self.verify_video(path, require_audio=True),
            timeout=300,
        )
        self.run_cli(
            "T1.6",
            ["main.py", "run", "test.mp4", "--config-file", "pipelines/examples/voiceover_en_to_vi.json"],
            lambda path: self.verify_video(path, require_audio=True),
            timeout=1200,
        )
        self.run_cli(
            "T1.7",
            ["main.py", "run", "test_input.mp4", "--pipeline-type", "audio_extract", "--target-language", "vi"],
            lambda path: self.verify_audio_file(path),
            timeout=240,
        )

    def run_t2_1_2_3(self) -> None:
        start = time.perf_counter()
        try:
            file_path = ROOT / "test_input.mp4"
            expected_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
            status, payload = self.upload_job(
                file_path,
                pipeline_type="low_level",
                payload={
                    "output_name": f"test-upload-cut-{self.timestamp}",
                    "operations": [
                        {"type": "cut", "params": {"start": 0, "duration": 5}},
                        {"type": "scale", "params": {"width": 1280, "height": 720}},
                    ],
                },
            )
            elapsed = time.perf_counter() - start
            if status != 200 or not isinstance(payload, dict) or "id" not in payload:
                raise AssertionError(f"upload failed: HTTP {status} {payload}")
            if payload.get("source_sha256") != expected_hash:
                raise AssertionError("source_sha256 mismatch")
            job_id = payload["id"]
            self.set_result("T2.1", "PASS", elapsed, f"job_id={job_id} sha256 ok")
        except Exception as exc:
            elapsed = time.perf_counter() - start
            self.error_section("T2.1", str(exc))
            self.set_result("T2.1", "FAIL", elapsed, str(exc))
            self.set_result("T2.2", "FAIL", 0.0, "blocked by T2.1 failure")
            self.set_result("T2.3", "FAIL", 0.0, "blocked by T2.1 failure")
            return

        sse_thread, events = self.start_sse_thread(job_id)
        start_wait = time.perf_counter()
        try:
            final_job = self.wait_job(job_id, timeout=180)
            elapsed_wait = time.perf_counter() - start_wait
            if final_job.get("status") != "done":
                raise AssertionError(f"job ended with status={final_job.get('status')}")
            result_items = final_job.get("metadata", {}).get("result_items") or []
            if not any(item.get("media_type") == "video" for item in result_items):
                raise AssertionError("metadata.result_items missing video")
            output_path = final_job.get("output_path")
            if not output_path or not (ROOT / output_path).exists() and not Path(output_path).exists():
                raise AssertionError(f"output_path missing on disk: {output_path}")
            self.set_result("T2.2", "PASS", elapsed_wait, f"status=done output={output_path}")
        except Exception as exc:
            elapsed_wait = time.perf_counter() - start_wait
            self.error_section("T2.2", str(exc))
            self.set_result("T2.2", "FAIL", elapsed_wait, str(exc))
        sse_thread.join(timeout=10)
        if any(line.startswith("data:") and '"progress"' in line for line in events):
            self.set_result("T2.3", "PASS", 0.0, f"SSE events captured={len(events)}")
        else:
            self.error_section("T2.3", f"No progress SSE data captured. Events={events}")
            self.set_result("T2.3", "FAIL", 0.0, "no progress SSE data captured")

    def run_phase2(self) -> None:
        self.run_t2_1_2_3()
        server, local_uri = self.start_static_file_server("T2.4", ROOT / "test_input.mp4")
        try:
            self.create_and_wait_job(
                "T2.4",
                {
                    "pipeline_type": "low_level",
                    "input_uri": local_uri,
                    "payload": {
                        "output_name": f"test-uri-flip-{self.timestamp}",
                        "operations": [
                            {"type": "cut", "params": {"start": 0, "duration": 3}},
                            {"type": "flip", "params": {"mode": "horizontal"}},
                        ],
                    },
                },
                timeout=180,
            )
        finally:
            server.shutdown()
            server.server_close()
        self.run_cancel_test()
        self.run_priority_test()
        self.run_admin_test()

    def create_and_wait_job(self, test_id: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any] | None:
        start = time.perf_counter()
        try:
            status, created = self.request_json("POST", "/jobs", payload)
            if status != 200 or not isinstance(created, dict) or "id" not in created:
                raise AssertionError(f"create failed: HTTP {status} {created}")
            final_job = self.wait_job(created["id"], timeout=timeout)
            elapsed = time.perf_counter() - start
            if final_job.get("status") != "done":
                raise AssertionError(f"job ended with status={final_job.get('status')} error={final_job.get('error')}")
            self.set_result(test_id, "PASS", elapsed, f"job_id={created['id']} done")
            return final_job
        except Exception as exc:
            elapsed = time.perf_counter() - start
            self.error_section(test_id, str(exc))
            self.set_result(test_id, "FAIL", elapsed, str(exc))
            return None

    def run_cancel_test(self) -> None:
        start = time.perf_counter()
        try:
            status, created = self.upload_job(
                ROOT / "test.mp4",
                pipeline_type="dubbing",
                payload={"target_language": "vi"},
                timeout=60,
            )
            if status != 200 or not isinstance(created, dict):
                raise AssertionError(f"create failed: HTTP {status} {created}")
            job_id = created["id"]
            time.sleep(2)
            cancel_status, cancelled = self.request_json("POST", f"/jobs/{job_id}/cancel")
            if cancel_status != 200 or not isinstance(cancelled, dict) or not cancelled.get("cancel_requested"):
                raise AssertionError(f"cancel failed: HTTP {cancel_status} {cancelled}")
            final_job = self.wait_job(job_id, timeout=90)
            elapsed = time.perf_counter() - start
            if final_job.get("status") != "cancelled":
                raise AssertionError(f"expected cancelled, got {final_job.get('status')}")
            self.set_result("T2.5", "PASS", elapsed, f"job_id={job_id} cancelled")
        except Exception as exc:
            elapsed = time.perf_counter() - start
            self.error_section("T2.5", str(exc))
            self.set_result("T2.5", "FAIL", elapsed, str(exc))

    def run_priority_test(self) -> None:
        start = time.perf_counter()
        created_jobs: list[dict[str, Any]] = []
        try:
            lock = threading.Lock()
            errors: list[str] = []

            def create(priority: int) -> None:
                status, created = self.request_json(
                    "POST",
                    "/jobs",
                    {
                        "pipeline_type": "low_level",
                        "input_path": "test_input.mp4",
                        "priority": priority,
                        "payload": {
                            "output_name": f"priority-{priority}-{self.timestamp}",
                            "operations": [{"type": "cut", "params": {"duration": 2}}],
                        },
                    },
                )
                with lock:
                    if status == 200 and isinstance(created, dict):
                        created_jobs.append(created)
                    else:
                        errors.append(f"priority={priority} create failed: HTTP {status} {created}")

            threads = [threading.Thread(target=create, args=(priority,), daemon=True) for priority in (0, 5, 10)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
            if errors:
                raise AssertionError("; ".join(errors))
            if len(created_jobs) != 3:
                raise AssertionError(f"expected 3 priority jobs, created {len(created_jobs)}")
            finals = [self.wait_job(job["id"], timeout=120) for job in created_jobs]
            started_order = sorted(
                [
                    (item.get("started_at") or item.get("created_at"), item.get("priority"), item.get("id"))
                    for item in finals
                ],
                key=lambda item: (item[0] or "", -int(item[1] or 0)),
            )
            elapsed = time.perf_counter() - start
            priority_10_start = next((item[0] for item in started_order if item[1] == 10), None)
            if priority_10_start is None:
                raise AssertionError(f"priority=10 job missing from finals; started_order={started_order}")
            lower_started_before_high = [
                item for item in started_order if int(item[1] or 0) < 10 and (item[0] or "") < priority_10_start
            ]
            if lower_started_before_high:
                raise AssertionError(
                    f"lower-priority jobs started before priority=10; "
                    f"violations={lower_started_before_high}; started_order={started_order}"
                )
            self.set_result("T2.6", "PASS", elapsed, f"priority=10 not preceded by lower priority; started_order={started_order}")
        except Exception as exc:
            elapsed = time.perf_counter() - start
            self.error_section("T2.6", str(exc))
            self.set_result("T2.6", "FAIL", elapsed, str(exc))

    def run_admin_test(self) -> None:
        start = time.perf_counter()
        try:
            status, html = self.request_json("GET", "/admin", timeout=20)
            jobs_status, jobs = self.request_json("GET", "/admin/jobs?limit=10", timeout=20)
            done_status, done_jobs = self.request_json("GET", "/admin/jobs?status=done&limit=10", timeout=20)
            elapsed = time.perf_counter() - start
            if status != 200 or not isinstance(html, str) or "AI Video Engine Admin" not in html:
                raise AssertionError(f"admin HTML failed: HTTP {status}")
            if jobs_status != 200 or not isinstance(jobs, dict) or "items" not in jobs:
                raise AssertionError(f"admin jobs failed: HTTP {jobs_status}")
            if done_status != 200 or not isinstance(done_jobs, dict) or "items" not in done_jobs:
                raise AssertionError(f"admin status filter failed: HTTP {done_status}")
            self.set_result("T2.7", "PASS", elapsed, "admin HTML, jobs JSON, and status filter loaded")
        except Exception as exc:
            elapsed = time.perf_counter() - start
            self.error_section("T2.7", str(exc))
            self.set_result("T2.7", "FAIL", elapsed, str(exc))

    def run_phase3(self) -> None:
        self.run_command(
            "T3.1",
            [
                sys.executable,
                "scripts/test_webhook_live.py",
                "--base-url",
                self.base_url,
                "--api-key",
                self.api_key,
                "--webhook-port",
                "9999",
                "--input-uri",
                "https://sample-videos.com/video321/mp4/240/big_buck_bunny_240p_1mb.mp4",
                "--timeout",
                "120",
            ],
            timeout=160,
        )
        # Translate command result after the fact from the log marker by rerunning quickly is not needed here.
        # Store conservative status based on the previous command result line.
        # The command wrapper logged an ERROR SECTION if it failed.
        if "T3.1" not in self.results:
            # Infer by checking the last command was successful is handled manually here via a lightweight direct call.
            pass
        self.run_webhook_failed_test()
        self.run_webhook_cancelled_test()

    def run_webhook_script_status(self) -> None:
        pass

    def run_webhook_failed_test(self) -> None:
        start = time.perf_counter()
        server, url, capture = self.start_webhook_server("T3.2")
        try:
            status, created = self.request_json(
                "POST",
                "/jobs",
                {
                    "pipeline_type": "low_level",
                    "input_uri": "https://example.com/nonexistent.mp4",
                    "payload": {
                        "webhook_url": url,
                        "operations": [{"type": "cut", "params": {"duration": 3}}],
                    },
                },
            )
            if status != 200 or not isinstance(created, dict):
                raise AssertionError(f"create failed: HTTP {status} {created}")
            final_job = self.wait_job(created["id"], timeout=90)
            capture.event.wait(20)
            elapsed = time.perf_counter() - start
            if final_job.get("status") != "failed":
                raise AssertionError(f"expected failed, got {final_job.get('status')}")
            if not capture.payloads:
                raise AssertionError("webhook not received")
            event = capture.payloads[0]
            if event.get("event") != "job.failed" or not event.get("error_detail"):
                raise AssertionError(f"unexpected webhook payload: {event}")
            self.set_result("T3.2", "PASS", elapsed, f"event={event.get('event')} code={event.get('error_detail', {}).get('code')}")
        except Exception as exc:
            elapsed = time.perf_counter() - start
            self.error_section("T3.2", str(exc))
            self.set_result("T3.2", "FAIL", elapsed, str(exc))
        finally:
            server.shutdown()
            server.server_close()

    def run_webhook_cancelled_test(self) -> None:
        start = time.perf_counter()
        server, url, capture = self.start_webhook_server("T3.3")
        try:
            status, created = self.upload_job(
                ROOT / "test.mp4",
                pipeline_type="dubbing",
                payload={"target_language": "vi", "webhook_url": url},
                timeout=60,
            )
            if status != 200 or not isinstance(created, dict):
                raise AssertionError(f"create failed: HTTP {status} {created}")
            job_id = created["id"]
            time.sleep(2)
            self.request_json("POST", f"/jobs/{job_id}/cancel")
            final_job = self.wait_job(job_id, timeout=90)
            capture.event.wait(20)
            elapsed = time.perf_counter() - start
            if final_job.get("status") != "cancelled":
                raise AssertionError(f"expected cancelled, got {final_job.get('status')}")
            if not capture.payloads:
                raise AssertionError("webhook not received")
            event = capture.payloads[0]
            if event.get("event") != "job.cancelled":
                raise AssertionError(f"unexpected webhook payload: {event}")
            self.set_result("T3.3", "PASS", elapsed, f"event={event.get('event')}")
        except Exception as exc:
            elapsed = time.perf_counter() - start
            self.error_section("T3.3", str(exc))
            self.set_result("T3.3", "FAIL", elapsed, str(exc))
        finally:
            server.shutdown()
            server.server_close()

    def run_phase4(self) -> None:
        start = time.perf_counter()
        try:
            Request("http://localhost:5678", method="GET")
            with urlopen("http://localhost:5678", timeout=3):
                n8n_note = "n8n reachable, but workflow import/execution is manual and was not automated"
                status = "BLOCKED"
        except Exception:
            n8n_note = "n8n is not reachable at http://localhost:5678"
            status = "BLOCKED"
        elapsed = time.perf_counter() - start
        for test_id in ("W1", "W2", "W3", "W4", "W5"):
            self.set_result(test_id, status, elapsed, n8n_note)

    def run_phase5(self) -> None:
        self.run_concurrent_jobs()
        self.run_large_file()
        self.run_invalid_pipeline()
        self.run_cache_observation()
        self.run_rate_limit()

    def run_concurrent_jobs(self) -> None:
        start = time.perf_counter()
        try:
            ids: list[str] = []
            for index in range(1, 5):
                status, created = self.request_json(
                    "POST",
                    "/jobs",
                    {
                        "pipeline_type": "low_level",
                        "input_path": "test_input.mp4",
                        "payload": {
                            "output_name": f"stress-{index}-{self.timestamp}",
                            "operations": [{"type": "cut", "params": {"duration": 3}}],
                        },
                    },
                )
                if status != 200 or not isinstance(created, dict):
                    raise AssertionError(f"create stress job failed: HTTP {status} {created}")
                ids.append(created["id"])
            finals = [self.wait_job(job_id, timeout=180) for job_id in ids]
            elapsed = time.perf_counter() - start
            if not all(item.get("status") == "done" for item in finals):
                raise AssertionError(f"not all jobs done: {[item.get('status') for item in finals]}")
            self.set_result("T5.1", "PASS", elapsed, f"completed jobs={ids}")
        except Exception as exc:
            elapsed = time.perf_counter() - start
            self.error_section("T5.1", str(exc))
            self.set_result("T5.1", "FAIL", elapsed, str(exc))

    def run_large_file(self) -> None:
        start = time.perf_counter()
        try:
            status, created = self.upload_job(
                ROOT / "test.mp4",
                pipeline_type="low_level",
                payload={"operations": [{"type": "cut", "params": {"start": 0, "duration": 10}}]},
                timeout=60,
            )
            if status != 200 or not isinstance(created, dict):
                raise AssertionError(f"upload failed: HTTP {status} {created}")
            final_job = self.wait_job(created["id"], timeout=120)
            elapsed = time.perf_counter() - start
            if final_job.get("status") != "done":
                raise AssertionError(f"expected done, got {final_job.get('status')}")
            self.set_result("T5.2", "PASS", elapsed, f"job_id={created['id']} done in {elapsed:.2f}s")
        except Exception as exc:
            elapsed = time.perf_counter() - start
            self.error_section("T5.2", str(exc))
            self.set_result("T5.2", "FAIL", elapsed, str(exc))

    def run_rate_limit(self) -> None:
        start = time.perf_counter()
        counts: dict[int, int] = {}
        try:
            for _ in range(self.rate_limit_per_minute + 5):
                status, _payload = self.request_json("GET", "/jobs/__rate_limit_probe__", auth=True, timeout=5)
                counts[status] = counts.get(status, 0) + 1
            elapsed = time.perf_counter() - start
            if counts.get(429, 0) >= 1:
                self.set_result("T5.3", "PASS", elapsed, f"status_counts={counts}")
            else:
                raise AssertionError(f"expected 429 but got status_counts={counts}; protected API routes should be rate limited")
        except Exception as exc:
            elapsed = time.perf_counter() - start
            self.error_section("T5.3", str(exc))
            self.set_result("T5.3", "FAIL", elapsed, str(exc))

    def run_invalid_pipeline(self) -> None:
        start = time.perf_counter()
        try:
            status, payload = self.request_json(
                "POST",
                "/jobs",
                {"pipeline_type": "nonexistent", "input_path": "test.mp4", "payload": {}},
            )
            elapsed = time.perf_counter() - start
            detail = payload.get("detail") if isinstance(payload, dict) else str(payload)
            if status == 400 and "supported" in str(detail):
                self.set_result("T5.4", "PASS", elapsed, f"HTTP 400 detail={detail}")
            else:
                raise AssertionError(f"expected HTTP 400 with supported list, got HTTP {status} {payload}")
        except Exception as exc:
            elapsed = time.perf_counter() - start
            self.error_section("T5.4", str(exc))
            self.set_result("T5.4", "FAIL", elapsed, str(exc))

    def run_cache_observation(self) -> None:
        start = time.perf_counter()
        try:
            durations: list[float] = []
            ids: list[str] = []
            for index in (1, 2):
                job_start = time.perf_counter()
                status, created = self.request_json(
                    "POST",
                    "/jobs",
                    {
                        "pipeline_type": "low_level",
                        "input_path": "test_input.mp4",
                        "payload": {
                            "output_name": f"cache-{index}-{self.timestamp}",
                            "operations": [{"type": "cut", "params": {"duration": 3}}],
                        },
                    },
                )
                if status != 200 or not isinstance(created, dict):
                    raise AssertionError(f"cache job {index} create failed: HTTP {status} {created}")
                ids.append(created["id"])
                final_job = self.wait_job(created["id"], timeout=120)
                if final_job.get("status") != "done":
                    raise AssertionError(f"cache job {index} status={final_job.get('status')}")
                durations.append(time.perf_counter() - job_start)
            elapsed = time.perf_counter() - start
            note = f"job_ids={ids} durations={durations[0]:.2f}s/{durations[1]:.2f}s"
            self.set_result("T5.5", "PASS", elapsed, note)
        except Exception as exc:
            elapsed = time.perf_counter() - start
            self.error_section("T5.5", str(exc))
            self.set_result("T5.5", "FAIL", elapsed, str(exc))

    def run_all(self) -> None:
        self.log(f"Real-world test run started. root={ROOT}")
        self.log(f"log_path={self.log_path}")
        self.run_phase1()
        api_started = self.start_api()
        if not api_started:
            for test_id in (
                "T2.1",
                "T2.2",
                "T2.3",
                "T2.4",
                "T2.5",
                "T2.6",
                "T2.7",
                "T3.1",
                "T3.2",
                "T3.3",
                "T5.1",
                "T5.2",
                "T5.3",
                "T5.4",
                "T5.5",
            ):
                self.set_result(test_id, "BLOCKED", 0.0, "API server failed to start")
        else:
            self.run_phase2()
            self.run_phase3_with_script_result()
            self.run_phase5()
        self.run_phase4()
        self.write_status()
        self.log(f"Real-world test run finished. results={self.results_path}")

    def run_phase3_with_script_result(self) -> None:
        server, local_uri = self.start_static_file_server("T3.1", ROOT / "test_input.mp4")
        try:
            rc, output, elapsed = self.run_command(
                "T3.1",
                [
                    sys.executable,
                    "scripts/test_webhook_live.py",
                    "--base-url",
                    self.base_url,
                    "--api-key",
                    self.api_key,
                    "--webhook-port",
                    "0",
                    "--input-uri",
                    local_uri,
                    "--timeout",
                    "120",
                ],
                timeout=170,
            )
            if rc == 0 and "PASSED live webhook test" in output:
                self.set_result("T3.1", "PASS", elapsed, "PASSED live webhook test")
            else:
                self.set_result("T3.1", "FAIL", elapsed, "script failed; see ERROR SECTION in log")
        finally:
            server.shutdown()
            server.server_close()
        self.run_webhook_failed_test()
        self.run_webhook_cancelled_test()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TEST_PLAN_REALWORLD.md and write raw logs/results.")
    parser.add_argument("--base-url", default=os.getenv("BASE_URL", "http://127.0.0.1:6666"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY", "realworld-test-key"))
    parser.add_argument("--timestamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--log-dir", default="logs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runner = RealWorldRunner(
        base_url=args.base_url,
        api_key=args.api_key,
        log_dir=ROOT / args.log_dir,
        timestamp=args.timestamp,
    )
    try:
        runner.run_all()
    finally:
        runner.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
