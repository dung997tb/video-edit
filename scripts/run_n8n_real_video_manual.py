from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
TOOLS_FFMPEG = ROOT / "tools" / "ffmpeg" / "ffmpeg-8.1-essentials_build" / "bin" / "ffmpeg.exe"
TOOLS_FFPROBE = ROOT / "tools" / "ffmpeg" / "ffmpeg-8.1-essentials_build" / "bin" / "ffprobe.exe"
TERMINAL_STATUSES = {"done", "failed", "cancelled"}
DEFAULT_API_KEY = "codex-real-video-test-key"


@dataclass(slots=True)
class N8nCase:
    id: str
    group: str
    name: str
    pipeline_type: str
    input_path: str
    payload: dict[str, Any]
    expected: str = "video"
    timeout_seconds: int = 900
    poll_seconds: int = 2

    def to_workflow_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "group": self.group,
            "name": self.name,
            "pipeline_type": self.pipeline_type,
            "input_path": self.input_path,
            "payload": self.payload,
            "expected": self.expected,
            "timeout_seconds": self.timeout_seconds,
            "poll_seconds": self.poll_seconds,
        }


@dataclass(slots=True)
class VerificationResult:
    case_id: str
    status: str
    verification: str
    output_path: str | None = None
    duration: float | None = None
    has_video: bool | None = None
    has_audio: bool | None = None
    artifact_count: int | None = None
    error: str | None = None
    job_id: str | None = None
    group: str | None = None


@dataclass(slots=True)
class CollectorState:
    run_dir: Path
    cases: dict[str, N8nCase]
    ffprobe_path: Path
    api_base: str = ""
    api_key: str = DEFAULT_API_KEY
    require_smoke_gate: bool = True
    started_at: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)
    verifications: dict[str, VerificationResult] = field(default_factory=dict)
    callbacks: list[dict[str, Any]] = field(default_factory=list)
    events_seen: int = 0
    smoke_passed: bool = False

    @property
    def events_path(self) -> Path:
        return self.run_dir / "events.jsonl"

    @property
    def ffprobe_dir(self) -> Path:
        return self.run_dir / "ffprobe"

    def write_event(self, event_type: str, payload: dict[str, Any]) -> None:
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "event": event_type,
            "payload": payload,
        }
        with self.lock:
            self.events_seen += 1
            if event_type == "webhook_callback":
                self.callbacks.append(payload)
            if event_type in {"negative_result", "group_result", "case_failed", "group_failed"}:
                case_id = str(payload.get("case_id") or "")
                if not case_id and event_type == "group_failed":
                    case_id = f"{payload.get('group') or 'group'}_FAILED"
                if case_id:
                    result = VerificationResult(
                        case_id=case_id,
                        status=str(payload.get("status") or "FAIL"),
                        verification=str(payload.get("verification") or payload.get("note") or event_type),
                        output_path=payload.get("output_path"),
                        error=payload.get("error"),
                        job_id=payload.get("job_id"),
                        group=payload.get("group"),
                    )
                    self.verifications[case_id] = result
                    if case_id == "SMOKE_01" and result.status == "PASS":
                        self.smoke_passed = True
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def verify_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        case_id = str(payload.get("case_id") or "")
        if not case_id or case_id not in self.cases:
            return {"status": "FAIL", "verification": "unknown_case", "case_id": case_id}
        case = self.cases[case_id]
        job = payload.get("job") or {}
        child_jobs = payload.get("child_jobs") or []
        result = self._verify(case, job, child_jobs)
        with self.lock:
            self.verifications[case_id] = result
            if case_id == "SMOKE_01" and result.status == "PASS":
                self.smoke_passed = True
        self.write_event("case_verified", asdict(result))
        return asdict(result)

    def _verify(self, case: N8nCase, job: dict[str, Any], child_jobs: list[dict[str, Any]]) -> VerificationResult:
        job_id = str(job.get("id") or job.get("job_id") or "")
        status = str(job.get("status") or "")
        if case.expected == "fanout":
            return self._verify_fanout(case, child_jobs, job_id)
        if status != "done":
            return VerificationResult(
                case_id=case.id,
                status="FAIL",
                verification=f"job_status_{status or 'missing'}",
                error=str(job.get("error") or ""),
                job_id=job_id,
                group=case.group,
            )

        output_path = self._resolve_output_path(case, job)
        if case.expected == "frames":
            count = self._count_fresh_files(output_path, ("*.jpg", "*.jpeg", "*.png"))
            return VerificationResult(
                case_id=case.id,
                status="PASS" if count > 0 else "FAIL",
                verification="ok" if count > 0 else "missing_frames",
                output_path=str(output_path),
                artifact_count=count,
                job_id=job_id,
                group=case.group,
            )
        if case.expected == "segments":
            segments = sorted(output_path.glob("segment_*.mp4")) if output_path.exists() else []
            ok = bool(segments)
            for segment in segments:
                probe = self._ffprobe(segment, f"{case.id}_{segment.stem}")
                if not _has_stream(probe, "video"):
                    ok = False
            return VerificationResult(
                case_id=case.id,
                status="PASS" if ok else "FAIL",
                verification="ok" if ok else "missing_or_bad_segments",
                output_path=str(output_path),
                artifact_count=len(segments),
                job_id=job_id,
                group=case.group,
            )
        if not output_path.exists() or output_path.stat().st_size <= 0:
            return VerificationResult(
                case_id=case.id,
                status="FAIL",
                verification="missing_or_empty_output",
                output_path=str(output_path),
                job_id=job_id,
                group=case.group,
            )

        probe = self._ffprobe(output_path, case.id)
        duration = _duration(probe)
        has_video = _has_stream(probe, "video")
        has_audio = _has_stream(probe, "audio")
        if case.expected == "audio":
            ok = has_audio
            verification = "ok" if ok else "no_audio_stream"
        else:
            ok = has_video
            verification = "ok" if ok else "no_video_stream"
        return VerificationResult(
            case_id=case.id,
            status="PASS" if ok else "FAIL",
            verification=verification,
            output_path=str(output_path),
            duration=duration,
            has_video=has_video,
            has_audio=has_audio,
            artifact_count=1,
            job_id=job_id,
            group=case.group,
        )

    def _verify_fanout(self, case: N8nCase, child_jobs: list[dict[str, Any]], parent_job_id: str) -> VerificationResult:
        done_children = [item for item in child_jobs if item.get("status") == "done"]
        output_paths = [str(item.get("output_path") or "") for item in done_children if item.get("output_path")]
        unique_paths = sorted(set(output_paths))
        ok = len(done_children) >= 3 and len(unique_paths) >= 3
        for index, raw_path in enumerate(unique_paths):
            path = _local_path(raw_path)
            if not path.exists() or path.stat().st_size <= 0:
                ok = False
                continue
            probe = self._ffprobe(path, f"{case.id}_child_{index + 1}")
            if not _has_stream(probe, "video"):
                ok = False
        return VerificationResult(
            case_id=case.id,
            status="PASS" if ok else "FAIL",
            verification="ok" if ok else "fanout_children_incomplete",
            output_path=", ".join(unique_paths) if unique_paths else None,
            artifact_count=len(done_children),
            job_id=parent_job_id,
            group=case.group,
        )

    def _resolve_output_path(self, case: N8nCase, job: dict[str, Any]) -> Path:
        output_path = str(job.get("output_path") or "").strip()
        if output_path:
            return _local_path(output_path)
        output_name = str(case.payload.get("output_name") or case.id)
        if case.expected == "frames":
            return ROOT / "output" / output_name / "frames"
        if case.expected == "segments":
            return ROOT / "output" / output_name / "segments"
        return ROOT / "output" / output_name / "final.mp4"

    def _count_fresh_files(self, directory: Path, patterns: tuple[str, ...]) -> int:
        if not directory.exists() or not directory.is_dir():
            return 0
        count = 0
        for pattern in patterns:
            count += len(list(directory.glob(pattern)))
        return count

    def _ffprobe(self, path: Path, label: str) -> dict[str, Any]:
        safe_label = _slug(label)
        target = self.ffprobe_dir / f"{safe_label}.json"
        result = subprocess.run(
            [
                str(self.ffprobe_path),
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
            timeout=45,
        )
        payload = json.loads(result.stdout or "{}") if result.returncode == 0 else {"error": result.stderr.strip()}
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def summary(self) -> dict[str, Any]:
        with self.lock:
            results = [asdict(item) for item in self.verifications.values()]
            callbacks = list(self.callbacks)
            smoke_passed = self.smoke_passed
            events_seen = self.events_seen
        total = len(results)
        passed = sum(1 for item in results if item["status"] == "PASS")
        failed = sum(1 for item in results if item["status"] == "FAIL")
        return {
            "run_dir": str(self.run_dir),
            "total_results": total,
            "passed": passed,
            "failed": failed,
            "smoke_passed": smoke_passed,
            "events_seen": events_seen,
            "callbacks": callbacks,
            "results": sorted(results, key=lambda item: item["case_id"]),
        }

    def run_group(self, group_name: str, callback_url: str | None = None) -> dict[str, Any]:
        if group_name == "03_webhook_batch":
            if not callback_url:
                raise ValueError("callback_url is required for 03_webhook_batch")
            return self._run_webhook_batch(callback_url)
        if group_name == "04_negative_recovery":
            return self._run_negative_recovery()
        return self._run_case_group(group_name)

    def _request_json(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
        *,
        auth: bool = False,
        allow_error: bool = False,
        timeout: float = 60,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if auth:
            headers["X-API-Key"] = self.api_key
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                status = int(response.status)
                text = response.read().decode("utf-8", errors="replace")
        except HTTPError as error:
            status = int(error.code)
            text = error.read().decode("utf-8", errors="replace")
        except URLError as error:
            if allow_error:
                return {"ok": False, "status": 0, "data": {"error": str(error)}, "text": str(error)}
            raise RuntimeError(f"{method} {url} failed: {error}") from error
        payload: dict[str, Any] = {}
        if text:
            try:
                parsed = json.loads(text)
                payload = parsed if isinstance(parsed, dict) else {"items": parsed}
            except json.JSONDecodeError:
                payload = {"raw": text}
        ok = 200 <= status < 300
        if not ok and not allow_error:
            raise RuntimeError(f"{method} {url} failed: HTTP {status} {text}")
        return {"ok": ok, "status": status, "data": payload, "text": text}

    def _api_url(self, path: str) -> str:
        if not self.api_base:
            raise RuntimeError("collector API base is not configured")
        return f"{self.api_base.rstrip('/')}/{path.lstrip('/')}"

    def _assert_smoke_gate(self, group_name: str) -> None:
        if not self.require_smoke_gate or group_name == "00_smoke":
            return
        if not self.smoke_passed:
            self.write_event("group_blocked", {"group": group_name, "reason": "smoke gate has not passed"})
            raise RuntimeError("Smoke gate has not passed. Run workflow 00 Smoke first.")

    def _create_job(self, case: N8nCase) -> dict[str, Any]:
        response = self._request_json(
            "POST",
            self._api_url("/jobs"),
            {
                "pipeline_type": case.pipeline_type,
                "input_path": case.input_path,
                "payload": case.payload,
            },
            auth=True,
            timeout=60,
        )
        return response["data"]

    def _get_job(self, job_id: str) -> dict[str, Any]:
        return self._request_json("GET", self._api_url(f"/jobs/{job_id}"), auth=True, timeout=30)["data"]

    def _cancel_job(self, job_id: str) -> dict[str, Any]:
        return self._request_json(
            "POST",
            self._api_url(f"/jobs/{job_id}/cancel"),
            {},
            auth=True,
            allow_error=True,
            timeout=30,
        )["data"]

    def _list_jobs(self) -> list[dict[str, Any]]:
        payload = self._request_json("GET", self._api_url("/jobs?limit=200"), auth=True, timeout=30)["data"]
        items = payload.get("items") or []
        return items if isinstance(items, list) else []

    def _wait_job(self, job_id: str, timeout_seconds: int | float, poll_seconds: int | float) -> dict[str, Any]:
        deadline = time.time() + float(timeout_seconds)
        job = self._get_job(job_id)
        while str(job.get("status") or "") not in TERMINAL_STATUSES:
            if time.time() >= deadline:
                raise TimeoutError(f"Timeout waiting for job {job_id}; last status={job.get('status')}")
            time.sleep(max(1.0, float(poll_seconds)))
            job = self._get_job(job_id)
            self.write_event(
                "case_poll",
                {"job_id": job_id, "status": job.get("status"), "progress": job.get("progress")},
            )
        return job

    def _wait_fanout_children(self, parent_job_id: str, timeout_seconds: int) -> list[dict[str, Any]]:
        deadline = time.time() + timeout_seconds
        children: list[dict[str, Any]] = []
        while time.time() < deadline:
            children = [
                job
                for job in self._list_jobs()
                if isinstance(job.get("payload"), dict) and job["payload"].get("parent_job_id") == parent_job_id
            ]
            if len(children) >= 3 and all(str(job.get("status") or "") in TERMINAL_STATUSES for job in children):
                return children
            time.sleep(5)
        return children

    def _run_case(self, case: N8nCase) -> dict[str, Any]:
        self.write_event(
            "case_start",
            {
                "case_id": case.id,
                "group": case.group,
                "name": case.name,
                "started_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        try:
            created = self._create_job(case)
            job_id = str(created.get("id") or "")
            self.write_event("case_created", {"case_id": case.id, "job_id": job_id, "status": created.get("status")})
            final_job = self._wait_job(job_id, case.timeout_seconds, case.poll_seconds)
            child_jobs: list[dict[str, Any]] = []
            if case.expected == "fanout" and final_job.get("status") == "done":
                child_jobs = self._wait_fanout_children(str(final_job.get("id") or job_id), case.timeout_seconds)
            verification = self.verify_job({"case_id": case.id, "job": final_job, "child_jobs": child_jobs})
            self.write_event(
                "case_done",
                {"case_id": case.id, "group": case.group, "job_id": final_job.get("id"), "verification": verification},
            )
            return {"case_id": case.id, "status": verification["status"], "verification": verification, "job": final_job}
        except Exception as error:  # noqa: BLE001 - evidence collector must preserve failures and continue.
            failure = {"case_id": case.id, "group": case.group, "status": "FAIL", "error": str(error)}
            self.write_event("case_failed", failure)
            return failure

    def _run_case_group(self, group_name: str) -> dict[str, Any]:
        self._assert_smoke_gate(group_name)
        group_cases = [case for case in self.cases.values() if case.group == group_name]
        if not group_cases:
            raise ValueError(f"unknown group: {group_name}")
        self.write_event("group_start", {"group": group_name, "total": len(group_cases)})
        results = [self._run_case(case) for case in group_cases]
        passed = sum(1 for item in results if item.get("status") == "PASS")
        failed = len(results) - passed
        self.write_event("group_done", {"group": group_name, "passed": passed, "failed": failed, "total": len(results)})
        return {"group": group_name, "passed": passed, "failed": failed, "total": len(results), "results": results}

    def _run_webhook_job(self, case_id: str, event_kind: str, body: dict[str, Any], cancel_after_seconds: float = 0) -> dict[str, Any]:
        self.write_event("webhook_case_start", {"case_id": case_id, "expected_event": event_kind})
        created = self._request_json("POST", self._api_url("/jobs"), body, auth=True, timeout=60)["data"]
        job_id = str(created.get("id") or "")
        if cancel_after_seconds > 0:
            time.sleep(cancel_after_seconds)
            self._cancel_job(job_id)
        final_job = self._wait_job(job_id, 900, 2)
        self.write_event(
            "webhook_case_terminal",
            {"case_id": case_id, "expected_event": event_kind, "job_id": job_id, "status": final_job.get("status")},
        )
        return final_job

    def _run_webhook_batch(self, callback_url: str) -> dict[str, Any]:
        group_name = "03_webhook_batch"
        self._assert_smoke_gate(group_name)
        self.write_event("group_start", {"group": group_name, "callback_url": callback_url})
        short_video = str((ROOT / "test_input.mp4").resolve())
        speech_video = str((ROOT / "test.mp4").resolve())
        completed_job = self._run_webhook_job(
            "WB_CALLBACK_DONE",
            "job.completed",
            {
                "pipeline_type": "low_level",
                "input_path": short_video,
                "payload": {
                    "output_name": "WB_CALLBACK_DONE",
                    "webhook_url": callback_url,
                    "operations": [{"name": "cut", "start": 0, "duration": 4}],
                    "cache_bust": True,
                },
            },
        )
        failed_job = self._run_webhook_job(
            "WB_CALLBACK_FAILED",
            "job.failed",
            {
                "pipeline_type": "low_level",
                "input_path": short_video,
                "payload": {
                    "output_name": "WB_CALLBACK_FAILED",
                    "webhook_url": callback_url,
                    "operations": [{"name": "overlay"}],
                    "cache_bust": True,
                },
            },
        )
        cancelled_job = self._run_webhook_job(
            "WB_CALLBACK_CANCELLED",
            "job.cancelled",
            {
                "pipeline_type": "low_level",
                "input_path": speech_video,
                "payload": {
                    "output_name": "WB_CALLBACK_CANCELLED",
                    "webhook_url": callback_url,
                    "operations": [
                        {"name": "blur_bg_portrait", "output_width": 1080, "output_height": 1920},
                        {"name": "auto_zoom", "interval_seconds": 5},
                        {"name": "pad_border", "size": 10, "color": "#000000"},
                    ],
                    "cache_bust": True,
                },
            },
            cancel_after_seconds=1,
        )

        batch_cases = [case for case in self.cases.values() if case.group == group_name]
        created = [self._create_job(case) for case in batch_cases]
        batch_results = []
        for case, created_job in zip(batch_cases, created, strict=True):
            final_job = self._wait_job(str(created_job.get("id") or ""), case.timeout_seconds, case.poll_seconds)
            verification = self.verify_job({"case_id": case.id, "job": final_job, "child_jobs": []})
            batch_results.append({"case_id": case.id, "status": verification["status"], "verification": verification})

        required_events = {"job.completed", "job.failed", "job.cancelled"}
        deadline = time.time() + 90
        while time.time() < deadline:
            seen = {str(item.get("event") or "") for item in self.callbacks}
            if required_events.issubset(seen):
                break
            time.sleep(3)
        seen = {str(item.get("event") or "") for item in self.callbacks}
        missing_callbacks = sorted(required_events - seen)
        self.write_event(
            "group_result",
            {
                "case_id": "WB_CALLBACK_EVENTS",
                "group": group_name,
                "status": "PASS" if not missing_callbacks else "FAIL",
                "verification": "all_callbacks_received" if not missing_callbacks else f"missing callbacks: {', '.join(missing_callbacks)}",
            },
        )
        self.write_event(
            "group_result",
            {
                "case_id": "WB_BATCH_ALL",
                "group": group_name,
                "status": "PASS" if all(item["status"] == "PASS" for item in batch_results) else "FAIL",
                "verification": f"batch pass {sum(1 for item in batch_results if item['status'] == 'PASS')}/{len(batch_results)}",
            },
        )
        payload = {
            "group": group_name,
            "webhook_statuses": {
                "completed": completed_job.get("status"),
                "failed": failed_job.get("status"),
                "cancelled": cancelled_job.get("status"),
            },
            "batch_results": batch_results,
            "missing_callbacks": missing_callbacks,
        }
        self.write_event("group_done", payload)
        return payload

    def _record_negative(self, results: list[dict[str, Any]], case_id: str, passed: bool, note: str, extra: dict[str, Any] | None = None) -> None:
        payload = {
            "case_id": case_id,
            "group": "04_negative_recovery",
            "status": "PASS" if passed else "FAIL",
            "verification": note,
            **(extra or {}),
        }
        self.write_event("negative_result", payload)
        results.append(payload)

    def _run_negative_recovery(self) -> dict[str, Any]:
        group_name = "04_negative_recovery"
        self._assert_smoke_gate(group_name)
        self.write_event("group_start", {"group": group_name})
        results: list[dict[str, Any]] = []
        short_video = str((ROOT / "test_input.mp4").resolve())
        speech_video = str((ROOT / "test.mp4").resolve())

        unsupported = self._request_json(
            "POST",
            self._api_url("/jobs"),
            {"pipeline_type": "nonexistent", "input_path": short_video, "payload": {}},
            auth=True,
            allow_error=True,
        )
        self._record_negative(results, "NEG_01_UNSUPPORTED_PIPELINE", unsupported["status"] == 400, f"HTTP {unsupported['status']}", unsupported["data"])

        missing_input = self._request_json(
            "POST",
            self._api_url("/jobs"),
            {
                "pipeline_type": "low_level",
                "input_path": "missing-real-video-input.mp4",
                "payload": {"operations": [{"name": "cut", "start": 0, "duration": 2}]},
            },
            auth=True,
            allow_error=True,
        )
        self._record_negative(results, "NEG_02_MISSING_INPUT", missing_input["status"] == 400, f"HTTP {missing_input['status']}", missing_input["data"])

        cancel_created = self._request_json(
            "POST",
            self._api_url("/jobs"),
            {
                "pipeline_type": "low_level",
                "input_path": speech_video,
                "payload": {
                    "output_name": "NEG_03_CANCEL_RUNNING",
                    "operations": [
                        {"name": "blur_bg_portrait", "output_width": 1080, "output_height": 1920},
                        {"name": "auto_zoom", "interval_seconds": 5},
                        {"name": "pad_border", "size": 10, "color": "#000000"},
                    ],
                    "cache_bust": True,
                },
            },
            auth=True,
        )["data"]
        time.sleep(1)
        self._cancel_job(str(cancel_created.get("id") or ""))
        cancelled = self._wait_job(str(cancel_created.get("id") or ""), 300, 1)
        self._record_negative(
            results,
            "NEG_03_CANCEL_RUNNING",
            str(cancelled.get("status") or "") in {"cancelled", "failed"},
            f"terminal {cancelled.get('status')}",
            {"job_id": cancelled.get("id"), "output_path": cancelled.get("output_path")},
        )

        timeout_passed = False
        timeout_job: dict[str, Any] | None = None
        try:
            timeout_job = self._request_json(
                "POST",
                self._api_url("/jobs"),
                {
                    "pipeline_type": "low_level",
                    "input_path": short_video,
                    "payload": {
                        "output_name": "NEG_04_EXPECTED_POLL_TIMEOUT",
                        "operations": [{"name": "cut", "start": 0, "duration": 8}],
                        "cache_bust": True,
                    },
                },
                auth=True,
            )["data"]
            self._wait_job(str(timeout_job.get("id") or ""), 0.001, 1)
        except Exception as error:  # noqa: BLE001 - the timeout path is the behavior under test.
            timeout_passed = "Timeout waiting for job" in str(error)
        if timeout_job and timeout_job.get("id"):
            try:
                cleanup_job = self._wait_job(str(timeout_job["id"]), 300, 1)
                self._record_negative(
                    results,
                    "NEG_04_EXPECTED_POLL_TIMEOUT",
                    timeout_passed,
                    "timeout path observed and job cleaned up" if timeout_passed else "timeout was not observed",
                    {"job_id": cleanup_job.get("id"), "output_path": cleanup_job.get("output_path")},
                )
            except Exception as error:  # noqa: BLE001
                self._record_negative(
                    results,
                    "NEG_04_EXPECTED_POLL_TIMEOUT",
                    timeout_passed,
                    "timeout observed; cleanup polling failed" if timeout_passed else str(error),
                    {"job_id": timeout_job["id"]},
                )
        else:
            self._record_negative(results, "NEG_04_EXPECTED_POLL_TIMEOUT", False, "timeout job was not created")

        passed = sum(1 for item in results if item["status"] == "PASS")
        failed = len(results) - passed
        self.write_event("group_done", {"group": group_name, "passed": passed, "failed": failed, "total": len(results)})
        return {"group": group_name, "passed": passed, "failed": failed, "results": results}


def _local_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT / path


def _has_stream(probe: dict[str, Any], codec_type: str) -> bool:
    return any(item.get("codec_type") == codec_type for item in probe.get("streams", []))


def _duration(probe: dict[str, Any]) -> float | None:
    raw = probe.get("format", {}).get("duration")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class CollectorHandler(BaseHTTPRequestHandler):
    state: CollectorState

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/health"):
            self._json({"status": "ok", "run_dir": str(self.state.run_dir)})
            return
        if self.path.startswith("/gate/smoke"):
            self._json({"smoke_passed": self.state.smoke_passed})
            return
        if self.path.startswith("/callbacks"):
            self._json({"items": self.state.callbacks})
            return
        if self.path.startswith("/summary"):
            self._json(self.state.summary())
            return
        self._json({"detail": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        payload = self._read_json()
        if self.path.startswith("/event"):
            event_type = str(payload.get("event") or "event")
            self.state.write_event(event_type, dict(payload.get("payload") or {}))
            self._json({"ok": True})
            return
        if self.path.startswith("/verify"):
            self._json(self.state.verify_job(payload))
            return
        if self.path.startswith("/run-group"):
            try:
                group_name = str(payload.get("group") or "")
                callback_url = payload.get("callback_url")
                self._json(self.state.run_group(group_name, str(callback_url) if callback_url else None))
            except Exception as error:  # noqa: BLE001 - n8n should receive the failure as JSON evidence.
                self.state.write_event(
                    "group_failed",
                    {
                        "group": payload.get("group"),
                        "error": str(error),
                    },
                )
                self._json({"ok": False, "error": str(error)}, status=500)
            return
        self._json({"detail": "not found"}, status=404)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {"raw": raw}

    def _json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _resolve_tool(env_name: str, binary_name: str, bundled: Path) -> Path:
    env_value = os.environ.get(env_name)
    candidates = [Path(env_value)] if env_value else []
    candidates.append(bundled)
    found = shutil.which(binary_name)
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"{binary_name} not found. Set {env_name} or install tools/ffmpeg.")


def _slug(value: str) -> str:
    allowed = []
    for char in value.strip().lower():
        if char.isalnum():
            allowed.append(char)
        elif char in {"-", "_"}:
            allowed.append(char)
        else:
            allowed.append("_")
    return "".join(allowed).strip("_") or "item"


def _id() -> str:
    return str(uuid.uuid4())


def ffprobe_json(path: Path, ffprobe_path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [str(ffprobe_path), "-v", "error", "-show_entries", "format=duration", "-show_streams", "-of", "json", str(path)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=True,
    )
    return json.loads(result.stdout or "{}")


def ffmpeg_asset(ffmpeg_path: Path, command: list[str | Path]) -> None:
    subprocess.run(
        [str(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-y", *[str(item) for item in command]],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=True,
    )


def prepare_assets(input_path: Path, asset_dir: Path, prefix: str, ffmpeg_path: Path) -> dict[str, str]:
    asset_dir.mkdir(parents=True, exist_ok=True)
    aux_video = asset_dir / f"{prefix}_aux.mp4"
    broll_video = asset_dir / f"{prefix}_broll.mp4"
    overlay_image = asset_dir / f"{prefix}_overlay.jpg"
    watermark_image = asset_dir / f"{prefix}_watermark.png"
    ffmpeg_asset(ffmpeg_path, ["-ss", "2", "-i", input_path, "-t", "12", "-c", "copy", aux_video])
    ffmpeg_asset(ffmpeg_path, ["-ss", "4", "-i", input_path, "-t", "8", "-c", "copy", broll_video])
    ffmpeg_asset(ffmpeg_path, ["-ss", "1", "-i", input_path, "-frames:v", "1", "-vf", "scale=320:-1", overlay_image])
    ffmpeg_asset(
        ffmpeg_path,
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=white@0.0:s=320x120:d=1",
            "-vf",
            "format=rgba,drawbox=x=0:y=0:w=320:h=120:color=0x1A73E8@0.75:t=fill,drawbox=x=14:y=14:w=292:h=92:color=white@0.35:t=4",
            "-frames:v",
            "1",
            watermark_image,
        ],
    )
    return {
        "MAIN_VIDEO": str(input_path),
        "AUX_VIDEO": str(aux_video),
        "BROLL_VIDEO": str(broll_video),
        "OVERLAY_IMAGE": str(overlay_image),
        "WATERMARK_IMAGE": str(watermark_image),
    }


def even_at_most(value: int, maximum: int) -> int:
    value = max(2, min(value, maximum))
    return value if value % 2 == 0 else value - 1


def build_low_level_cases(input_path: Path, assets: dict[str, str], probe: dict[str, Any]) -> list[N8nCase]:
    video_stream = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"), {})
    width = int(video_stream.get("width") or 1280)
    height = int(video_stream.get("height") or 720)
    crop_w = even_at_most(width, 960)
    crop_h = even_at_most(height, 540)
    aux = assets["AUX_VIDEO"]
    overlay = assets["OVERLAY_IMAGE"]
    watermark = assets["WATERMARK_IMAGE"]
    ops = [
        ("RV_L01", "cut", {"start": 0, "end": 8}),
        ("RV_L02", "speed", {"factor": 1.25}),
        ("RV_L03", "flip", {"mode": "horizontal"}),
        ("RV_L04", "crop", {"width": crop_w, "height": crop_h, "x": 0, "y": 0}),
        ("RV_L05", "rotate", {"degrees": 8}),
        ("RV_L06", "scale", {"width": 1280, "height": 720}),
        ("RV_L07", "concat", {"inputs": [aux], "include_current": True}),
        ("RV_L08", "overlay", {"overlay_path": overlay, "x": 30, "y": 30, "overlay_width": 240}),
        ("RV_L09", "watermark", {"watermark_path": watermark, "x": 32, "y": 32, "opacity": 0.7}),
        ("RV_L10", "denoise", {"luma_spatial": 4, "chroma_spatial": 3}),
        ("RV_L11", "color_grade", {"brightness": 0.05, "contrast": 1.1, "saturation": 1.15}),
        ("RV_L12", "pad_border", {"size": 30, "color": "white"}),
        ("RV_L13", "blur_bg_portrait", {"output_width": 1080, "output_height": 1920}),
        ("RV_L14", "loop", {"times": 2}),
        ("RV_L15", "filter_duration", {"min_seconds": 1, "max_seconds": 600}),
        ("RV_L16", "delogo", {"x": 0, "y": 0, "w": min(200, width), "h": min(80, height), "mode": "blur"}),
        ("RV_L17", "content_variant", {"grain": 3, "hue_shift": 2.0, "sat_factor": 1.02}),
        ("RV_L18", "hstack", {"second_video": aux, "layout": "horizontal"}),
        ("RV_L19", "split_screen", {"b_roll_video": aux, "audio_source": "mix"}),
        ("RV_L20", "chromakey", {"background_video": aux, "color": "#00FF00", "similarity": 0.3, "blend": 0.1}),
        ("RV_L21", "grid", {"videos": [aux, aux, aux], "cols": 2, "rows": 2}),
        ("RV_L22", "convert", {"output_format": "mp4"}),
        ("RV_L23", "random_mirror", {"flip_probability": 0.4, "segment_duration": 3.0, "seed": 42}),
        ("RV_L24", "platform_reframe", {"preset": "9:16"}),
        ("RV_L25", "auto_zoom", {"interval_seconds": 4, "zoom_factor": 1.1, "output_width": width, "output_height": height}),
        ("RV_L26", "audio_trim", {"start": 0, "duration": 10}),
        ("RV_L27", "audio_speed", {"factor": 1.15}),
        ("RV_L28", "audio_volume", {"volume": 0.6}),
        ("RV_L29", "audio_fade", {"type": "in", "duration": 1.0}),
        ("RV_L30", "audio_normalize", {"i": -16, "tp": -1.5, "lra": 11}),
        ("RV_L31", "audio_pitch", {"semitones": 2, "preserve_tempo": True}),
        ("RV_L32", "visual_blur", {"luma_radius": 3, "luma_power": 1}),
        ("RV_L33", "visual_sharpen", {"luma_msize_x": 5, "luma_msize_y": 5, "luma_amount": 1.2}),
        ("RV_L34", "visual_grayscale", {}),
        ("RV_L35", "visual_vignette", {"angle": "PI/5"}),
    ]
    cases: list[N8nCase] = []
    for case_id, op_name, params in ops:
        cases.append(
            N8nCase(
                id=case_id,
                group="01_low_level",
                name=op_name,
                pipeline_type="low_level",
                input_path=str(input_path),
                payload={
                    "output_name": f"{case_id}_{op_name}",
                    "operations": [{"name": op_name, **params}],
                    "cache_bust": True,
                },
                timeout_seconds=900 if op_name in {"blur_bg_portrait", "hstack", "grid"} else 480,
            )
        )
    return cases


def build_pipeline_cases(input_path: Path, assets: dict[str, str]) -> list[N8nCase]:
    broll = assets["BROLL_VIDEO"]
    base = str(input_path)
    definitions: list[N8nCase] = [
        N8nCase("RV_P01", "02_pipeline_ai", "dubbing_vi", "dubbing", base, {"output_name": "RV_P01_dubbing_vi", "target_language": "vi", "source_language": "auto", "burn_subtitles": False, "cache_bust": True}, timeout_seconds=3600),
        N8nCase("RV_P02", "02_pipeline_ai", "dubbing_burned", "dubbing", base, {"output_name": "RV_P02_dubbing_burned", "target_language": "vi", "source_language": "auto", "burn_subtitles": True, "cache_bust": True}, timeout_seconds=3600),
        N8nCase("RV_P03", "02_pipeline_ai", "subtitle_burned", "subtitle", base, {"output_name": "RV_P03_subtitle_burned", "target_language": "vi", "source_language": "auto", "burn_subtitles": True, "cache_bust": True}, timeout_seconds=2400),
        N8nCase("RV_P04", "02_pipeline_ai", "subtitle_karaoke", "subtitle", base, {"output_name": "RV_P04_subtitle_karaoke", "target_language": "vi", "source_language": "auto", "subtitle_style": "karaoke", "burn_subtitles": True, "cache_bust": True}, timeout_seconds=2400),
        N8nCase("RV_P05", "02_pipeline_ai", "silence_cut", "silence_cut", base, {"output_name": "RV_P05_silence_cut", "min_silence_duration": 0.5, "silence_threshold_db": -35, "cache_bust": True}, timeout_seconds=1200),
        N8nCase("RV_P06", "02_pipeline_ai", "semantic_edit", "semantic_edit", base, {"output_name": "RV_P06_semantic_edit", "command": "make_tiktok_short", "target_duration": 30, "source_language": "auto", "cache_bust": True}, timeout_seconds=1800),
        N8nCase("RV_P07", "02_pipeline_ai", "semantic_silence_cut", "semantic_edit", base, {"output_name": "RV_P07_semantic_silence_cut", "command": "silence_cut", "min_silence_duration": 0.5, "silence_threshold_db": -35, "cache_bust": True}, timeout_seconds=1800),
        N8nCase("RV_P08", "02_pipeline_ai", "face_track_portrait", "face_track_portrait", base, {"output_name": "RV_P08_face_track_portrait", "output_width": 1080, "output_height": 1920, "cache_bust": True}, timeout_seconds=1800),
        N8nCase("RV_P09", "02_pipeline_ai", "auto_broll", "auto_broll", base, {"output_name": "RV_P09_auto_broll", "source_language": "auto", "keyword_map": {"": broll}, "cache_bust": True}, timeout_seconds=1800),
        N8nCase("RV_P10", "02_pipeline_ai", "ad_video", "ad_video", base, {"output_name": "RV_P10_ad_video", "ad_text": "Day la video quang cao thu nghiem cho bo test real video.", "tts_voice": "vi-VN-HoaiMyNeural", "cache_bust": True}, timeout_seconds=2400),
        N8nCase("RV_P11", "02_pipeline_ai", "workflow_dag", "workflow", base, {"output_name": "RV_P11_workflow_dag", "workflow": {"nodes": {"border": {"type": "video.pad_border", "params": {"size": 12, "color": "white"}}, "export": {"type": "media.finalize", "depends_on": ["border"]}}}, "cache_bust": True}, timeout_seconds=900),
        N8nCase("RV_P12", "02_pipeline_ai", "multilang", "multilang-dubbing", base, {"output_name": "RV_P12_multilang", "source_language": "auto", "target_languages": ["vi", "ja", "ko"], "segment_retry_on_overflow": False, "cache_bust": True}, expected="fanout", timeout_seconds=5400),
        N8nCase("RV_P13", "02_pipeline_ai", "split_video", "split_video", base, {"output_name": "RV_P13_split_video", "segment_seconds": 30, "cache_bust": True}, expected="segments", timeout_seconds=1200),
        N8nCase("RV_P14", "02_pipeline_ai", "audio_extract", "audio-extract", base, {"output_name": "RV_P14_audio_extract", "sample_rate": 44100, "cache_bust": True}, expected="audio", timeout_seconds=900),
        N8nCase("RV_P15", "02_pipeline_ai", "extract_frames", "extract_frames", base, {"output_name": "RV_P15_extract_frames", "interval_seconds": 5, "cache_bust": True}, expected="frames", timeout_seconds=900),
    ]
    return definitions


def build_smoke_case(input_path: Path) -> N8nCase:
    return N8nCase(
        id="SMOKE_01",
        group="00_smoke",
        name="api_cut_smoke",
        pipeline_type="low_level",
        input_path=str(input_path),
        payload={
            "output_name": "SMOKE_01_api_cut",
            "operations": [{"name": "cut", "start": 0, "duration": 4}],
            "cache_bust": True,
        },
        timeout_seconds=240,
        poll_seconds=1,
    )


def build_batch_cases(input_path: Path) -> list[N8nCase]:
    cases = []
    for index in range(1, 5):
        cases.append(
            N8nCase(
                id=f"WB_BATCH_{index}",
                group="03_webhook_batch",
                name=f"batch_{index}",
                pipeline_type="low_level",
                input_path=str(input_path),
                payload={
                    "output_name": f"WB_BATCH_{index}",
                    "operations": [{"name": "cut", "start": 0, "duration": 3 + index}],
                    "cache_bust": True,
                },
                expected="video",
                timeout_seconds=300,
                poll_seconds=1,
            )
        )
    return cases


def build_cases(run_dir: Path, ffmpeg_path: Path, ffprobe_path: Path) -> list[N8nCase]:
    short_video = (ROOT / "test_input.mp4").resolve()
    speech_video = (ROOT / "test.mp4").resolve()
    if not short_video.exists():
        raise FileNotFoundError(f"missing test video: {short_video}")
    if not speech_video.exists():
        raise FileNotFoundError(f"missing test video: {speech_video}")
    asset_dir = run_dir / "assets"
    short_assets = prepare_assets(short_video, asset_dir, "short", ffmpeg_path)
    speech_assets = prepare_assets(speech_video, asset_dir, "speech", ffmpeg_path)
    short_probe = ffprobe_json(short_video, ffprobe_path)
    cases = [build_smoke_case(short_video)]
    cases.extend(build_low_level_cases(short_video, short_assets, short_probe))
    cases.extend(build_pipeline_cases(speech_video, speech_assets))
    cases.extend(build_batch_cases(short_video))
    return cases


def manual_trigger(pos: tuple[int, int] = (240, 300)) -> dict[str, Any]:
    return {
        "id": _id(),
        "name": "Manual Trigger",
        "type": "n8n-nodes-base.manualTrigger",
        "typeVersion": 1,
        "position": list(pos),
        "parameters": {},
    }


def webhook_trigger(path: str, pos: tuple[int, int] = (240, 520)) -> dict[str, Any]:
    return {
        "id": _id(),
        "name": "Callback Webhook",
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": list(pos),
        "parameters": {
            "httpMethod": "POST",
            "path": path,
            "responseMode": "onReceived",
            "responseCode": 204,
        },
        "webhookId": _id(),
    }


def code_node(name: str, code: str, pos: tuple[int, int] = (560, 300)) -> dict[str, Any]:
    return {
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": list(pos),
        "parameters": {
            "mode": "runOnceForAllItems",
            "language": "javaScript",
            "jsCode": code,
        },
    }


def http_request_node(
    name: str,
    url: str,
    body: dict[str, Any] | str,
    pos: tuple[int, int] = (560, 300),
    *,
    timeout_ms: int = 3_600_000,
) -> dict[str, Any]:
    raw_body = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    return {
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4,
        "position": list(pos),
        "parameters": {
            "method": "POST",
            "url": url,
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Content-Type", "value": "application/json"},
                ]
            },
            "sendBody": True,
            "contentType": "raw",
            "rawContentType": "application/json",
            "body": raw_body,
            "options": {"timeout": timeout_ms},
        },
    }


def common_js(
    *,
    api_candidates: list[str],
    collector_candidates: list[str],
    api_key: str,
    require_smoke_gate: bool,
) -> str:
    return f"""
const apiCandidates = {json.dumps(api_candidates)};
const collectorCandidates = {json.dumps(collector_candidates)};
const apiKey = {json.dumps(api_key)};
const requireSmokeGate = {json.dumps(require_smoke_gate)};
const terminalStatuses = new Set(['done', 'failed', 'cancelled']);

async function sleep(ms) {{
  await new Promise(resolve => setTimeout(resolve, ms));
}}

async function requestJson(method, url, body, options = {{}}) {{
  const headers = {{ 'Accept': 'application/json' }};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.auth) headers['X-API-Key'] = apiKey;
  const response = await fetch(url, {{
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  }});
  const text = await response.text();
  let payload = {{}};
  if (text) {{
    try {{ payload = JSON.parse(text); }} catch (_error) {{ payload = {{ raw: text }}; }}
  }}
  if (!response.ok && !options.allowError) {{
    throw new Error(`${{method}} ${{url}} failed: HTTP ${{response.status}} ${{text}}`);
  }}
  return {{ ok: response.ok, status: response.status, data: payload, text }};
}}

async function firstHealthy(candidates, label) {{
  const errors = [];
  for (const candidate of candidates) {{
    try {{
      const response = await requestJson('GET', `${{candidate}}/health`, undefined, {{ allowError: true }});
      if (response.ok) return candidate.replace(/\\/+$/, '');
      errors.push(`${{candidate}} -> HTTP ${{response.status}}`);
    }} catch (error) {{
      errors.push(`${{candidate}} -> ${{error.message}}`);
    }}
  }}
  throw new Error(`No reachable ${{label}} endpoint. ${{errors.join(' | ')}}`);
}}

const collectorBase = await firstHealthy(collectorCandidates, 'collector');
const apiBase = await firstHealthy(apiCandidates, 'Video API');

async function emit(event, payload) {{
  try {{
    await requestJson('POST', `${{collectorBase}}/event`, {{ event, payload }}, {{ allowError: true }});
  }} catch (_error) {{}}
}}

async function verifyCase(testCase, job, childJobs = []) {{
  const response = await requestJson('POST', `${{collectorBase}}/verify`, {{
    case_id: testCase.id,
    job,
    child_jobs: childJobs,
  }});
  return response.data;
}}

async function assertSmokeGate(groupName) {{
  if (!requireSmokeGate || groupName === '00_smoke') return;
  const response = await requestJson('GET', `${{collectorBase}}/gate/smoke`);
  if (!response.data.smoke_passed) {{
    await emit('group_blocked', {{ group: groupName, reason: 'smoke gate has not passed' }});
    throw new Error('Smoke gate has not passed. Run workflow 00 Smoke first.');
  }}
}}

async function createJob(testCase) {{
  const body = {{
    pipeline_type: testCase.pipeline_type,
    input_path: testCase.input_path,
    payload: testCase.payload,
  }};
  const response = await requestJson('POST', `${{apiBase}}/jobs`, body, {{ auth: true }});
  return response.data;
}}

async function getJob(jobId) {{
  const response = await requestJson('GET', `${{apiBase}}/jobs/${{jobId}}`, undefined, {{ auth: true }});
  return response.data;
}}

async function cancelJob(jobId) {{
  const response = await requestJson('POST', `${{apiBase}}/jobs/${{jobId}}/cancel`, {{}}, {{ auth: true, allowError: true }});
  return response.data;
}}

async function listJobs() {{
  const response = await requestJson('GET', `${{apiBase}}/jobs?limit=200`, undefined, {{ auth: true }});
  return response.data.items || [];
}}

async function waitJob(jobId, timeoutSeconds, pollSeconds) {{
  const deadline = Date.now() + timeoutSeconds * 1000;
  let job = await getJob(jobId);
  while (!terminalStatuses.has(String(job.status))) {{
    if (Date.now() >= deadline) {{
      throw new Error(`Timeout waiting for job ${{jobId}}; last status=${{job.status}}`);
    }}
    await sleep(Math.max(1, pollSeconds) * 1000);
    job = await getJob(jobId);
    await emit('case_poll', {{ case_id: job.payload?.output_name || jobId, job_id: jobId, status: job.status, progress: job.progress }});
  }}
  return job;
}}

async function waitFanoutChildren(parentJobId, timeoutSeconds) {{
  const deadline = Date.now() + timeoutSeconds * 1000;
  let children = [];
  while (Date.now() < deadline) {{
    const jobs = await listJobs();
    children = jobs.filter(job => job.payload && job.payload.parent_job_id === parentJobId);
    if (children.length >= 3 && children.every(job => terminalStatuses.has(String(job.status)))) {{
      return children;
    }}
    await sleep(5000);
  }}
  return children;
}}

async function runCase(testCase) {{
  const startedAt = new Date().toISOString();
  await emit('case_start', {{ case_id: testCase.id, group: testCase.group, name: testCase.name, started_at: startedAt }});
  try {{
    const createResponse = await createJob(testCase);
    await emit('case_created', {{ case_id: testCase.id, job_id: createResponse.id, status: createResponse.status }});
    const finalJob = await waitJob(createResponse.id, testCase.timeout_seconds, testCase.poll_seconds);
    let childJobs = [];
    if (testCase.expected === 'fanout' && finalJob.status === 'done') {{
      childJobs = await waitFanoutChildren(finalJob.id, testCase.timeout_seconds);
    }}
    const verification = await verifyCase(testCase, finalJob, childJobs);
    await emit('case_done', {{ case_id: testCase.id, group: testCase.group, job_id: finalJob.id, verification }});
    return {{ case_id: testCase.id, status: verification.status, verification, job: finalJob, child_jobs: childJobs }};
  }} catch (error) {{
    const failure = {{ case_id: testCase.id, group: testCase.group, status: 'FAIL', error: error.message }};
    await emit('case_failed', failure);
    return failure;
  }}
}}
"""


def group_workflow_js(
    *,
    group_name: str,
    cases: list[N8nCase],
    api_candidates: list[str],
    collector_candidates: list[str],
    api_key: str,
    require_smoke_gate: bool,
) -> str:
    return (
        common_js(
            api_candidates=api_candidates,
            collector_candidates=collector_candidates,
            api_key=api_key,
            require_smoke_gate=require_smoke_gate,
        )
        + f"""
const groupName = {json.dumps(group_name)};
const cases = {json.dumps([case.to_workflow_payload() for case in cases], ensure_ascii=False, indent=2)};
await assertSmokeGate(groupName);
await emit('group_start', {{ group: groupName, total: cases.length }});
const results = [];
for (const testCase of cases) {{
  results.push(await runCase(testCase));
}}
const passed = results.filter(item => item.status === 'PASS').length;
const failed = results.length - passed;
await emit('group_done', {{ group: groupName, passed, failed, total: results.length }});
return [{{ json: {{ group: groupName, passed, failed, total: results.length, results }} }}];
"""
    )


def webhook_batch_js(
    *,
    api_candidates: list[str],
    collector_candidates: list[str],
    api_key: str,
    n8n_public_url: str,
    callback_path: str,
    require_smoke_gate: bool,
    batch_cases: list[N8nCase],
    short_video: Path,
    speech_video: Path,
) -> str:
    callback_url = f"{n8n_public_url.rstrip('/')}/webhook/{callback_path}"
    return (
        common_js(
            api_candidates=api_candidates,
            collector_candidates=collector_candidates,
            api_key=api_key,
            require_smoke_gate=require_smoke_gate,
        )
        + f"""
const groupName = '03_webhook_batch';
const callbackUrl = {json.dumps(callback_url)};
await assertSmokeGate(groupName);
await emit('group_start', {{ group: groupName, callback_url: callbackUrl }});

async function runWebhookJob(caseId, eventKind, body, cancelAfterMs = 0) {{
  await emit('webhook_case_start', {{ case_id: caseId, expected_event: eventKind }});
  const createResponse = await requestJson('POST', `${{apiBase}}/jobs`, body, {{ auth: true }});
  const jobId = createResponse.data.id;
  if (cancelAfterMs > 0) {{
    await sleep(cancelAfterMs);
    await cancelJob(jobId);
  }}
  const finalJob = await waitJob(jobId, 900, 2);
  await emit('webhook_case_terminal', {{ case_id: caseId, expected_event: eventKind, job_id: jobId, status: finalJob.status }});
  return finalJob;
}}

const completedJob = await runWebhookJob('WB_CALLBACK_DONE', 'job.completed', {{
  pipeline_type: 'low_level',
  input_path: {json.dumps(str(short_video))},
  payload: {{
    output_name: 'WB_CALLBACK_DONE',
    webhook_url: callbackUrl,
    operations: [{{ name: 'cut', start: 0, duration: 4 }}],
    cache_bust: true,
  }},
}});
const failedJob = await runWebhookJob('WB_CALLBACK_FAILED', 'job.failed', {{
  pipeline_type: 'low_level',
  input_path: {json.dumps(str(short_video))},
    payload: {{
    output_name: 'WB_CALLBACK_FAILED',
    webhook_url: callbackUrl,
    operations: [{{ name: 'overlay' }}],
    cache_bust: true,
  }},
}});
const cancelledJob = await runWebhookJob('WB_CALLBACK_CANCELLED', 'job.cancelled', {{
  pipeline_type: 'low_level',
  input_path: {json.dumps(str(speech_video))},
  payload: {{
    output_name: 'WB_CALLBACK_CANCELLED',
    webhook_url: callbackUrl,
    operations: [
      {{ name: 'blur_bg_portrait', output_width: 1080, output_height: 1920 }},
      {{ name: 'auto_zoom', interval_seconds: 5 }},
      {{ name: 'pad_border', size: 10, color: '#000000' }},
    ],
    cache_bust: true,
  }},
}}, 1000);

const batchCases = {json.dumps([case.to_workflow_payload() for case in batch_cases], ensure_ascii=False, indent=2)};
const created = await Promise.all(batchCases.map(testCase => createJob(testCase)));
const batchResults = [];
for (let i = 0; i < batchCases.length; i++) {{
  const finalJob = await waitJob(created[i].id, batchCases[i].timeout_seconds, batchCases[i].poll_seconds);
  const verification = await verifyCase(batchCases[i], finalJob, []);
  batchResults.push({{ case_id: batchCases[i].id, status: verification.status, verification }});
}}

const requiredEvents = new Set(['job.completed', 'job.failed', 'job.cancelled']);
let callbackItems = [];
const callbackDeadline = Date.now() + 90000;
while (Date.now() < callbackDeadline) {{
  const response = await requestJson('GET', `${{collectorBase}}/callbacks`);
  callbackItems = response.data.items || [];
  const seen = new Set(callbackItems.map(item => item.event));
  if ([...requiredEvents].every(event => seen.has(event))) break;
  await sleep(3000);
}}
const seenEvents = new Set(callbackItems.map(item => item.event));
const missingCallbacks = [...requiredEvents].filter(event => !seenEvents.has(event));
await emit('group_result', {{
  case_id: 'WB_CALLBACK_EVENTS',
  group: groupName,
  status: missingCallbacks.length === 0 ? 'PASS' : 'FAIL',
  verification: missingCallbacks.length === 0 ? 'all_callbacks_received' : `missing callbacks: ${{missingCallbacks.join(', ')}}`,
}});
await emit('group_result', {{
  case_id: 'WB_BATCH_ALL',
  group: groupName,
  status: batchResults.every(item => item.status === 'PASS') ? 'PASS' : 'FAIL',
  verification: `batch pass ${{batchResults.filter(item => item.status === 'PASS').length}}/${{batchResults.length}}`,
}});
await emit('group_done', {{
  group: groupName,
  webhook_statuses: {{
    completed: completedJob.status,
    failed: failedJob.status,
    cancelled: cancelledJob.status,
  }},
  batch_results: batchResults,
  missing_callbacks: missingCallbacks,
}});
return [{{ json: {{ group: groupName, callback_url: callbackUrl, missing_callbacks: missingCallbacks, batch_results: batchResults }} }}];
"""
    )


def callback_logger_js(*, collector_candidates: list[str]) -> str:
    return f"""
const collectorCandidates = {json.dumps(collector_candidates)};
async function requestJson(method, url, body, options = {{}}) {{
  const response = await fetch(url, {{
    method,
    headers: {{ 'Content-Type': 'application/json', 'Accept': 'application/json' }},
    body: body === undefined ? undefined : JSON.stringify(body),
  }});
  const text = await response.text();
  let payload = {{}};
  if (text) {{
    try {{ payload = JSON.parse(text); }} catch (_error) {{ payload = {{ raw: text }}; }}
  }}
  if (!response.ok && !options.allowError) throw new Error(`${{method}} ${{url}} failed: ${{response.status}} ${{text}}`);
  return payload;
}}
async function firstHealthy(candidates) {{
  for (const candidate of candidates) {{
    try {{
      const response = await requestJson('GET', `${{candidate}}/health`, undefined, {{ allowError: true }});
      if (response.status === 'ok' || response.run_dir) return candidate.replace(/\\/+$/, '');
    }} catch (_error) {{}}
  }}
  throw new Error('collector is not reachable');
}}
const collectorBase = await firstHealthy(collectorCandidates);
const input = $input.first().json;
const body = input.body || input;
await requestJson('POST', `${{collectorBase}}/event`, {{
  event: 'webhook_callback',
  payload: {{
    event: body.event || null,
    job_id: body.job_id || null,
    status: body.status || null,
    output_path: body.output_path || null,
    error: body.error || null,
    error_detail: body.error_detail || null,
  }},
}}, {{ allowError: true }});
return [{{ json: body }}];
"""


def negative_recovery_js(
    *,
    api_candidates: list[str],
    collector_candidates: list[str],
    api_key: str,
    require_smoke_gate: bool,
    short_video: Path,
    speech_video: Path,
) -> str:
    return (
        common_js(
            api_candidates=api_candidates,
            collector_candidates=collector_candidates,
            api_key=api_key,
            require_smoke_gate=require_smoke_gate,
        )
        + f"""
const groupName = '04_negative_recovery';
await assertSmokeGate(groupName);
await emit('group_start', {{ group: groupName }});
const results = [];
async function record(caseId, passed, note, extra = {{}}) {{
  const payload = {{ case_id: caseId, group: groupName, status: passed ? 'PASS' : 'FAIL', verification: note, ...extra }};
  await emit('negative_result', payload);
  results.push(payload);
}}

const unsupported = await requestJson('POST', `${{apiBase}}/jobs`, {{
  pipeline_type: 'nonexistent',
  input_path: {json.dumps(str(short_video))},
  payload: {{}},
}}, {{ auth: true, allowError: true }});
await record('NEG_01_UNSUPPORTED_PIPELINE', unsupported.status === 400, `HTTP ${{unsupported.status}}`, unsupported.data);

const missingInput = await requestJson('POST', `${{apiBase}}/jobs`, {{
  pipeline_type: 'low_level',
  input_path: 'missing-real-video-input.mp4',
  payload: {{ operations: [{{ name: 'cut', start: 0, duration: 2 }}] }},
}}, {{ auth: true, allowError: true }});
await record('NEG_02_MISSING_INPUT', missingInput.status === 400, `HTTP ${{missingInput.status}}`, missingInput.data);

const cancelCreate = await requestJson('POST', `${{apiBase}}/jobs`, {{
  pipeline_type: 'low_level',
  input_path: {json.dumps(str(speech_video))},
  payload: {{
    output_name: 'NEG_03_CANCEL_RUNNING',
    operations: [
      {{ name: 'blur_bg_portrait', output_width: 1080, output_height: 1920 }},
      {{ name: 'auto_zoom', interval_seconds: 5 }},
      {{ name: 'pad_border', size: 10, color: '#000000' }},
    ],
    cache_bust: true,
  }},
}}, {{ auth: true }});
await sleep(1000);
await cancelJob(cancelCreate.data.id);
const cancelled = await waitJob(cancelCreate.data.id, 300, 1);
await record('NEG_03_CANCEL_RUNNING', ['cancelled', 'failed'].includes(cancelled.status), `terminal ${{cancelled.status}}`, {{ job_id: cancelled.id, output_path: cancelled.output_path || null }});

let timeoutPassed = false;
let timeoutJob = null;
try {{
  const timeoutCreate = await requestJson('POST', `${{apiBase}}/jobs`, {{
    pipeline_type: 'low_level',
    input_path: {json.dumps(str(short_video))},
    payload: {{
      output_name: 'NEG_04_EXPECTED_POLL_TIMEOUT',
      operations: [{{ name: 'cut', start: 0, duration: 8 }}],
      cache_bust: true,
    }},
  }}, {{ auth: true }});
  timeoutJob = timeoutCreate.data;
  await waitJob(timeoutJob.id, 0.001, 1);
}} catch (error) {{
  timeoutPassed = String(error.message || '').includes('Timeout waiting for job');
}}
if (timeoutJob && timeoutJob.id) {{
  try {{
    const cleanupJob = await waitJob(timeoutJob.id, 300, 1);
    await record('NEG_04_EXPECTED_POLL_TIMEOUT', timeoutPassed, timeoutPassed ? 'timeout path observed and job cleaned up' : 'timeout was not observed', {{ job_id: cleanupJob.id, output_path: cleanupJob.output_path || null }});
  }} catch (error) {{
    await record('NEG_04_EXPECTED_POLL_TIMEOUT', timeoutPassed, timeoutPassed ? 'timeout observed; cleanup polling failed' : error.message, {{ job_id: timeoutJob.id }});
  }}
}} else {{
  await record('NEG_04_EXPECTED_POLL_TIMEOUT', false, 'timeout job was not created');
}}

const passed = results.filter(item => item.status === 'PASS').length;
const failed = results.length - passed;
await emit('group_done', {{ group: groupName, passed, failed, total: results.length }});
return [{{ json: {{ group: groupName, passed, failed, results }} }}];
"""
    )


def build_workflows(
    *,
    cases: list[N8nCase],
    run_id: str,
    api_key: str,
    api_candidates: list[str],
    collector_candidates: list[str],
    n8n_public_url: str,
    require_smoke_gate: bool,
) -> list[dict[str, Any]]:
    cases_by_group: dict[str, list[N8nCase]] = {}
    for case in cases:
        cases_by_group.setdefault(case.group, []).append(case)
    collector_base = collector_candidates[0].rstrip("/")
    workflows: list[dict[str, Any]] = []
    for group_name, display in [
        ("00_smoke", "00 Smoke"),
        ("01_low_level", "01 Low-Level Matrix"),
        ("02_pipeline_ai", "02 Pipeline AI Matrix"),
    ]:
        trigger = manual_trigger()
        runner = http_request_node(
            f"Run {display}",
            f"{collector_base}/run-group",
            {"group": group_name},
        )
        workflows.append(
            {
                "name": f"N8N Real Video {run_id} - {display}",
                "nodes": [trigger, runner],
                "connections": {trigger["name"]: {"main": [[{"node": runner["name"], "type": "main", "index": 0}]]}},
                "settings": {"executionOrder": "v1"},
            }
        )

    callback_path = f"n8n-real-video-callback-{run_id}"
    manual = manual_trigger((240, 240))
    webhook = webhook_trigger(callback_path, (240, 560))
    batch_runner = http_request_node(
        "Run Webhook And Batch",
        f"{collector_base}/run-group",
        {
            "group": "03_webhook_batch",
            "callback_url": f"{n8n_public_url.rstrip('/')}/webhook/{callback_path}",
        },
        (560, 240),
    )
    callback_logger = http_request_node(
        "Log Callback",
        f"{collector_base}/event",
        "={{ JSON.stringify({ event: 'webhook_callback', payload: ($json.body || $json) }) }}",
        (560, 560),
    )
    workflows.append(
        {
            "name": f"N8N Real Video {run_id} - 03 Webhook Batch",
            "nodes": [manual, webhook, batch_runner, callback_logger],
            "connections": {
                manual["name"]: {"main": [[{"node": batch_runner["name"], "type": "main", "index": 0}]]},
                webhook["name"]: {"main": [[{"node": callback_logger["name"], "type": "main", "index": 0}]]},
            },
            "settings": {"executionOrder": "v1"},
        }
    )

    neg_trigger = manual_trigger()
    neg_runner = http_request_node(
        "Run Negative Recovery",
        f"{collector_base}/run-group",
        {"group": "04_negative_recovery"},
    )
    workflows.append(
        {
            "name": f"N8N Real Video {run_id} - 04 Negative Recovery",
            "nodes": [neg_trigger, neg_runner],
            "connections": {neg_trigger["name"]: {"main": [[{"node": neg_runner["name"], "type": "main", "index": 0}]]}},
            "settings": {"executionOrder": "v1"},
        }
    )
    return workflows


def write_workflows(workflows: list[dict[str, Any]], workflow_dir: Path) -> list[Path]:
    workflow_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, workflow in enumerate(workflows):
        name = _slug(workflow["name"])
        path = workflow_dir / f"{index:02d}_{name}.json"
        path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
        paths.append(path)
    bundle = workflow_dir / "all_workflows_bundle.json"
    bundle.write_text(json.dumps(workflows, ensure_ascii=False, indent=2), encoding="utf-8")
    paths.append(bundle)
    return paths


def masked(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "***"
    return f"***{value[-4:]}"


def api_health(base_url: str, timeout: float = 2.0) -> bool:
    try:
        with urlopen(f"{base_url.rstrip('/')}/health", timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def start_api(args: argparse.Namespace, run_dir: Path, ffmpeg_path: Path, ffprobe_path: Path) -> subprocess.Popen[str] | None:
    if api_health(args.verify_api_url):
        return None
    env = os.environ.copy()
    env.update(
        {
            "API_PORT": str(args.api_port),
            "API_AUTH_ENABLED": "true",
            "API_SECRET_KEY": args.video_api_key,
            "API_ALLOW_INPUT_PATH": "true",
            "API_EMBEDDED_WORKER": "true",
            "WEBHOOKS_ENABLED": "true",
            "METRICS_ENABLED": "true",
            "FFMPEG_PATH": str(ffmpeg_path),
            "FFPROBE_PATH": str(ffprobe_path),
        }
    )
    stdout_path = run_dir / "api_stdout.log"
    handle = stdout_path.open("w", encoding="utf-8", errors="replace")
    process = subprocess.Popen(
        [sys.executable, "main.py", "api", "--host", "0.0.0.0", "--port", str(args.api_port)],
        cwd=ROOT,
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    process._codex_stdout_handle = handle  # type: ignore[attr-defined]
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            handle.close()
            raise RuntimeError(f"API exited early. See {stdout_path}")
        if api_health(args.verify_api_url):
            return process
        time.sleep(1)
    process.terminate()
    handle.close()
    raise RuntimeError(f"API did not become healthy at {args.verify_api_url}")


def stop_api(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    handle = getattr(process, "_codex_stdout_handle", None)
    if handle:
        handle.close()


def copy_app_log_slice(run_dir: Path) -> None:
    app_log = ROOT / "logs" / "app.log"
    target = run_dir / "api_app_slice.log"
    if not app_log.exists():
        target.write_text("logs/app.log not found\n", encoding="utf-8")
        return
    data = app_log.read_text(encoding="utf-8", errors="replace")
    target.write_text(data[-500_000:], encoding="utf-8")


def render_summary(state: CollectorState, run_dir: Path) -> None:
    summary = state.summary()
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# n8n Real Video Manual Test Summary",
        "",
        f"- Run dir: `{run_dir}`",
        f"- Passed: {summary['passed']}",
        f"- Failed: {summary['failed']}",
        f"- Smoke passed: {summary['smoke_passed']}",
        f"- Events seen: {summary['events_seen']}",
        "",
        "| Case | Status | Verification | Job | Output |",
        "|---|---|---|---|---|",
    ]
    for item in summary["results"]:
        lines.append(
            f"| {item['case_id']} | {item['status']} | {item['verification']} | {item.get('job_id') or ''} | `{item.get('output_path') or ''}` |"
        )
    if summary["callbacks"]:
        lines.extend(["", "## Webhook callbacks", ""])
        for callback in summary["callbacks"]:
            lines.append(f"- `{callback.get('event')}` job `{callback.get('job_id')}` status `{callback.get('status')}`")
    (run_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    rows = []
    for item in summary["results"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item['case_id']))}</td>"
            f"<td>{html.escape(str(item['status']))}</td>"
            f"<td>{html.escape(str(item['verification']))}</td>"
            f"<td>{html.escape(str(item.get('job_id') or ''))}</td>"
            f"<td>{html.escape(str(item.get('output_path') or ''))}</td>"
            "</tr>"
        )
    html_doc = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>n8n Real Video Summary</title>"
        "<style>body{font-family:Segoe UI,Arial,sans-serif;padding:24px}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px}"
        "th{background:#f4f4f4;text-align:left}</style></head><body>"
        "<h1>n8n Real Video Manual Test Summary</h1>"
        f"<p>Passed: {summary['passed']} | Failed: {summary['failed']} | Smoke passed: {summary['smoke_passed']}</p>"
        "<table><thead><tr><th>Case</th><th>Status</th><th>Verification</th><th>Job</th><th>Output</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>"
    )
    (run_dir / "summary.html").write_text(html_doc, encoding="utf-8")


def write_operator_guide(run_dir: Path, workflow_paths: list[Path], args: argparse.Namespace) -> None:
    lines = [
        "# Manual n8n Real Video Test Run",
        "",
        "## Services",
        "",
        f"- n8n UI: `{args.n8n_url}`",
        f"- Video API verify URL: `{args.verify_api_url}`",
        f"- Collector URL from host: `http://127.0.0.1:{args.collector_port}`",
        f"- Video API key: `{masked(args.video_api_key)}`",
        "",
        "## Import order",
        "",
    ]
    for path in workflow_paths:
        if path.name == "all_workflows_bundle.json":
            continue
        lines.append(f"- `{path}`")
    lines.extend(
        [
            "",
            "Import each workflow in n8n UI, keep them in this order, and run them one group at a time.",
            "Run `00 Smoke` first. Other workflows check the smoke gate and stop if smoke has not passed.",
            "",
            "For `03 Webhook Batch`, activate the workflow before running the Manual Trigger branch so the production webhook path can receive callbacks.",
            "",
            "Leave this Python process running while n8n workflows execute. Stop it with Ctrl+C after all groups finish; it writes final summary files.",
        ]
    )
    (run_dir / "OPERATOR_GUIDE.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and serve manual-UI n8n real-video test workflows.")
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--n8n-url", default="http://localhost:5678")
    parser.add_argument("--n8n-public-url", default="http://127.0.0.1:5678")
    parser.add_argument("--api-port", type=int, default=6666)
    parser.add_argument("--verify-api-url", default="", help="Host-side API URL used by the runner to check health.")
    parser.add_argument("--collector-port", type=int, default=18799)
    parser.add_argument("--video-api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--prepare-only", action="store_true", help="Generate workflows and reports without starting API/collector.")
    parser.add_argument("--no-smoke-gate", action="store_true")
    parser.add_argument("--open-n8n", action="store_true", help="Open n8n with the OS default browser.")
    args = parser.parse_args()
    if not args.verify_api_url:
        args.verify_api_url = f"http://127.0.0.1:{args.api_port}"
    return args


def main() -> int:
    args = parse_args()
    run_dir = ROOT / "test_runs" / f"n8n_real_video_{args.run_id}"
    workflow_dir = run_dir / "workflows"
    screenshot_dir = run_dir / "screenshots"
    ffprobe_dir = run_dir / "ffprobe"
    for directory in (run_dir, workflow_dir, screenshot_dir, ffprobe_dir):
        directory.mkdir(parents=True, exist_ok=True)

    ffmpeg_path = _resolve_tool("FFMPEG_PATH", "ffmpeg", TOOLS_FFMPEG)
    ffprobe_path = _resolve_tool("FFPROBE_PATH", "ffprobe", TOOLS_FFPROBE)
    cases = build_cases(run_dir, ffmpeg_path, ffprobe_path)
    cases_by_id = {case.id: case for case in cases}
    api_candidates = [f"http://host.docker.internal:{args.api_port}", f"http://127.0.0.1:{args.api_port}"]
    collector_candidates = [f"http://host.docker.internal:{args.collector_port}", f"http://127.0.0.1:{args.collector_port}"]
    workflows = build_workflows(
        cases=cases,
        run_id=args.run_id,
        api_key=args.video_api_key,
        api_candidates=api_candidates,
        collector_candidates=collector_candidates,
        n8n_public_url=args.n8n_public_url,
        require_smoke_gate=not args.no_smoke_gate,
    )
    workflow_paths = write_workflows(workflows, workflow_dir)
    (run_dir / "cases.json").write_text(
        json.dumps([case.to_workflow_payload() for case in cases], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest = {
        "run_id": args.run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(ROOT),
        "n8n_url": args.n8n_url,
        "n8n_public_url": args.n8n_public_url,
        "api_port": args.api_port,
        "collector_port": args.collector_port,
        "video_api_key": masked(args.video_api_key),
        "api_candidates": api_candidates,
        "collector_candidates": collector_candidates,
        "workflow_files": [str(path) for path in workflow_paths],
        "case_count": len(cases),
        "ffmpeg": str(ffmpeg_path),
        "ffprobe": str(ffprobe_path),
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_operator_guide(run_dir, workflow_paths, args)

    print(f"Run directory: {run_dir}")
    print(f"Workflow files: {workflow_dir}")
    print(f"Operator guide: {run_dir / 'OPERATOR_GUIDE.md'}")

    if args.prepare_only:
        render_summary(CollectorState(run_dir=run_dir, cases=cases_by_id, ffprobe_path=ffprobe_path), run_dir)
        return 0

    api_process: subprocess.Popen[str] | None = None
    server: ThreadingHTTPServer | None = None
    state = CollectorState(
        run_dir=run_dir,
        cases=cases_by_id,
        ffprobe_path=ffprobe_path,
        api_base=args.verify_api_url,
        api_key=args.video_api_key,
        require_smoke_gate=not args.no_smoke_gate,
    )
    CollectorHandler.state = state
    try:
        api_process = start_api(args, run_dir, ffmpeg_path, ffprobe_path)
        server = ThreadingHTTPServer(("0.0.0.0", args.collector_port), CollectorHandler)
        thread = threading.Thread(target=server.serve_forever, name="n8n-real-video-collector", daemon=True)
        thread.start()
        print(f"Video API: {args.verify_api_url}")
        print(f"Collector: http://127.0.0.1:{args.collector_port}")
        print("Import workflows in n8n UI and run them in order. Press Ctrl+C here after the run.")
        if args.open_n8n:
            import webbrowser

            webbrowser.open(args.n8n_url)
        stop_event = threading.Event()

        def _handle_signal(_signum: int, _frame: Any) -> None:
            stop_event.set()

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
        while not stop_event.wait(2):
            render_summary(state, run_dir)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        stop_api(api_process)
        copy_app_log_slice(run_dir)
        render_summary(state, run_dir)
        print(f"Final summary: {run_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
