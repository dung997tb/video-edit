from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _headers(api_key: str | None, *, json_body: bool = False) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _request_json(
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


def _request_text(method: str, base_url: str, path: str, *, api_key: str | None) -> str:
    request = Request(_url(base_url, path), headers=_headers(api_key), method=method)
    try:
        with urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise AssertionError(f"{method} {path} failed: {exc}") from exc


def _create_low_level_job(base_url: str, api_key: str | None, input_uri: str) -> dict[str, Any]:
    return _request_json(
        "POST",
        base_url,
        "/jobs",
        api_key=api_key,
        payload={
            "pipeline_type": "low_level",
            "input_uri": input_uri,
            "payload": {
                "operations": [
                    {"type": "cut", "params": {"start": 0, "duration": 3}},
                ]
            },
        },
    )


def run(args: argparse.Namespace) -> None:
    started_at = time.perf_counter()
    checks: list[str] = []

    health = _request_json("GET", args.base_url, "/health", api_key=args.api_key)
    assert health.get("status") == "ok", health
    checks.append("GET /health")

    created = _create_low_level_job(args.base_url, args.api_key, args.input_uri)
    job_id = created["id"]
    assert created["status"] in {"pending", "running", "done", "failed", "cancelled"}, created
    checks.append("POST /jobs")

    fetched = _request_json("GET", args.base_url, f"/jobs/{job_id}", api_key=args.api_key)
    assert fetched["id"] == job_id, fetched
    assert fetched["status"] in {"pending", "running", "done", "failed", "cancelled"}, fetched
    checks.append("GET /jobs/{id}")

    listed = _request_json("GET", args.base_url, "/jobs?limit=50", api_key=args.api_key)
    assert any(item["id"] == job_id for item in listed.get("items", [])), listed
    checks.append("GET /jobs")

    cancel_job = _create_low_level_job(args.base_url, args.api_key, args.input_uri)
    cancel_job_id = cancel_job["id"]
    cancelled = _request_json("POST", args.base_url, f"/jobs/{cancel_job_id}/cancel", api_key=args.api_key)
    assert cancelled["cancel_requested"] is True or cancelled["status"] == "cancelled", cancelled
    checks.append("POST /jobs/{id}/cancel")

    cancelled_status = None
    for _ in range(10):
        refreshed = _request_json("GET", args.base_url, f"/jobs/{cancel_job_id}", api_key=args.api_key)
        cancelled_status = refreshed["status"]
        if cancelled_status == "cancelled":
            break
        time.sleep(0.5)
    assert cancelled_status == "cancelled", {"job_id": cancel_job_id, "status": cancelled_status}

    cancelled_list = _request_json("GET", args.base_url, "/jobs?status=cancelled&limit=50", api_key=args.api_key)
    assert any(item["id"] == cancel_job_id for item in cancelled_list.get("items", [])), cancelled_list
    checks.append("GET /jobs?status=cancelled")

    admin_jobs = _request_json("GET", args.base_url, "/admin/jobs?limit=50", api_key=args.api_key)
    assert "items" in admin_jobs, admin_jobs
    checks.append("GET /admin/jobs")

    metrics = _request_text("GET", args.base_url, "/metrics", api_key=args.api_key)
    assert metrics.strip(), "metrics response is empty"
    checks.append("GET /metrics")

    elapsed = time.perf_counter() - started_at
    print("PASSED live API smoke test")
    print(f"Base URL: {args.base_url}")
    print(f"Checks: {len(checks)}")
    for check in checks:
        print(f"- {check}")
    print(f"Elapsed: {elapsed:.2f}s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live smoke test for AI Video Engine API.")
    parser.add_argument("--base-url", default="http://localhost:6666")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--input-uri", default="https://example.com/video.mp4")
    return parser.parse_args()


def main() -> int:
    try:
        run(parse_args())
    except AssertionError as exc:
        print("FAILED live API smoke test", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
