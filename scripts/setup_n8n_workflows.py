"""
setup_n8n_workflows.py
Tự động tạo toàn bộ workflow n8n test suite cho AI Video Engine.

Usage:
    python scripts/setup_n8n_workflows.py \
        --n8n-url http://localhost:5678 \
        --n8n-api-key YOUR_N8N_API_KEY \
        --video-api-url http://localhost:6666 \
        --video-api-key YOUR_VIDEO_API_KEY
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# ---------------------------------------------------------------------------
# n8n API helpers
# ---------------------------------------------------------------------------

def n8n_request(
    method: str,
    n8n_url: str,
    path: str,
    api_key: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Accept": "application/json",
        "X-N8N-API-KEY": api_key,
    }
    if data:
        headers["Content-Type"] = "application/json"
    req = Request(f"{n8n_url.rstrip('/')}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {path} failed: {exc}") from exc


def create_workflow(n8n_url: str, api_key: str, wf: dict[str, Any]) -> str:
    result = n8n_request("POST", n8n_url, "/api/v1/workflows", api_key, wf)
    return result["id"]


# ---------------------------------------------------------------------------
# Node builders
# ---------------------------------------------------------------------------

def _id() -> str:
    return str(uuid.uuid4())


def manual_trigger(pos: tuple[int, int] = (240, 300)) -> dict[str, Any]:
    return {
        "id": _id(), "name": "Manual Trigger",
        "type": "n8n-nodes-base.manualTrigger",
        "typeVersion": 1, "position": list(pos), "parameters": {},
    }


def webhook_trigger(path: str, pos: tuple[int, int] = (240, 300)) -> dict[str, Any]:
    return {
        "id": _id(), "name": "Webhook Trigger",
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2, "position": list(pos),
        "parameters": {
            "httpMethod": "POST",
            "path": path,
            "responseMode": "onReceived",
            "responseCode": 204,
        },
        "webhookId": _id(),
    }


def http_post_job(
    name: str,
    video_api_url: str,
    video_api_key: str,
    body: dict[str, Any],
    pos: tuple[int, int] = (460, 300),
) -> dict[str, Any]:
    headers = [{"name": "Content-Type", "value": "application/json"}]
    if video_api_key and video_api_key != "no-auth":
        headers.append({"name": "X-API-Key", "value": video_api_key})
    return {
        "id": _id(), "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4, "position": list(pos),
        "parameters": {
            "method": "POST",
            "url": f"{video_api_url}/jobs",
            "sendHeaders": True,
            "headerParameters": {"parameters": headers},
            "sendBody": True,
            "contentType": "raw",
            "rawContentType": "application/json",
            "body": json.dumps(body),
        },
    }



def http_get_job(
    video_api_url: str,
    video_api_key: str,
    pos: tuple[int, int] = (900, 300),
) -> dict[str, Any]:
    headers = []
    if video_api_key and video_api_key != "no-auth":
        headers.append({"name": "X-API-Key", "value": video_api_key})
    params: dict[str, Any] = {
        "method": "GET",
        "url": f'={video_api_url}/jobs/{{{{$("Set job_id").item.json.job_id}}}}',
    }
    if headers:
        params["sendHeaders"] = True
        params["headerParameters"] = {"parameters": headers}
    return {
        "id": _id(), "name": "Poll Job Status",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4, "position": list(pos),
        "parameters": params,
    }


def set_node(name: str, assignments: list[dict[str, str]], pos: tuple[int, int] = (680, 300)) -> dict[str, Any]:
    return {
        "id": _id(), "name": name,
        "type": "n8n-nodes-base.set",
        "typeVersion": 3, "position": list(pos),
        "parameters": {
            "mode": "manual",
            "assignments": {"assignments": assignments},
        },
    }


def if_node(name: str, condition_value: str, pos: tuple[int, int] = (1120, 300)) -> dict[str, Any]:
    return {
        "id": _id(), "name": name,
        "type": "n8n-nodes-base.if",
        "typeVersion": 2, "position": list(pos),
        "parameters": {
            "conditions": {
                "options": {"version": 2},
                "conditions": [
                    {
                        "id": _id(),
                        "leftValue": condition_value,
                        "rightValue": "done",
                        "operator": {"type": "string", "operation": "equals"},
                    }
                ],
            }
        },
    }


def wait_node(seconds: int = 3, pos: tuple[int, int] = (1340, 460)) -> dict[str, Any]:
    return {
        "id": _id(), "name": "Wait 3s",
        "type": "n8n-nodes-base.wait",
        "typeVersion": 1, "position": list(pos),
        "parameters": {"unit": "seconds", "amount": seconds},
        "webhookId": _id(),
    }


def respond_node(name: str, msg: str, pos: tuple[int, int] = (1340, 300)) -> dict[str, Any]:
    return {
        "id": _id(), "name": name,
        "type": "n8n-nodes-base.respondToWebhook",
        "typeVersion": 1, "position": list(pos),
        "parameters": {"responseBody": msg, "responseCode": 200},
    }


def code_node(name: str, code: str, pos: tuple[int, int] = (1120, 460)) -> dict[str, Any]:
    return {
        "id": _id(), "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2, "position": list(pos),
        "parameters": {"jsCode": code},
    }


# ---------------------------------------------------------------------------
# Workflow definitions
# ---------------------------------------------------------------------------

TERMINAL = {"done", "failed", "cancelled"}

POLL_JS = """
// Poll helper — used in Loop node
const status = $input.item.json.status;
if (['done', 'failed', 'cancelled'].includes(status)) {
  return [{json: {done: true, status, output_path: $input.item.json.output_path,
    result_items: ($input.item.json.metadata || {}).result_items || []}}];
}
return [{json: {done: false, status}}];
"""


def _conn(from_node: str, to_node: str, from_idx: int = 0) -> dict[str, Any]:
    """Build a single connection entry."""
    return {from_node: {"main": [[{"node": to_node, "type": "main", "index": from_idx}]]}}


def merge_connections(*conn_dicts: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for d in conn_dicts:
        for k, v in d.items():
            if k not in merged:
                merged[k] = v
            else:
                for branch_idx, targets in enumerate(v.get("main", [])):
                    if branch_idx >= len(merged[k]["main"]):
                        merged[k]["main"].append(targets)
                    else:
                        merged[k]["main"][branch_idx].extend(targets)
    return merged


def build_simple_poll_workflow(
    name: str,
    video_api_url: str,
    video_api_key: str,
    job_body: dict[str, Any],
) -> dict[str, Any]:
    """Standard 5-node poll workflow."""
    trigger = manual_trigger((240, 300))
    create = http_post_job("Create Job", video_api_url, video_api_key, job_body, (460, 300))
    save_id = set_node("Set job_id", [
        {"id": _id(), "name": "job_id", "value": '={{ $json.id }}', "type": "string"},
    ], (680, 300))
    poll = http_get_job(video_api_url, video_api_key, (900, 300))
    check = code_node("Check Done?", POLL_JS, (1120, 300))
    wait = wait_node(3, (1120, 460))
    done_set = set_node("Result OK", [
        {"id": _id(), "name": "status",     "value": '={{ $json.status }}',       "type": "string"},
        {"id": _id(), "name": "output",     "value": '={{ $json.output_path }}',  "type": "string"},
        {"id": _id(), "name": "items_count","value": '={{ ($json.result_items || []).length }}', "type": "number"},
    ], (1340, 300))

    nodes = [trigger, create, save_id, poll, check, wait, done_set]
    connections = merge_connections(
        {trigger["name"]: {"main": [[{"node": create["name"], "type": "main", "index": 0}]]}},
        {create["name"]: {"main": [[{"node": save_id["name"], "type": "main", "index": 0}]]}},
        {save_id["name"]: {"main": [[{"node": poll["name"], "type": "main", "index": 0}]]}},
        {poll["name"]: {"main": [[{"node": check["name"], "type": "main", "index": 0}]]}},
        # done branch → Result OK
        {check["name"]: {"main": [
            [{"node": done_set["name"], "type": "main", "index": 0}],  # done=true
            [{"node": wait["name"],     "type": "main", "index": 0}],  # done=false
        ]}},
        # wait → re-poll
        {wait["name"]: {"main": [[{"node": poll["name"], "type": "main", "index": 0}]]}},
    )
    return {
        "name": name,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
    }


def _wf(name: str, nodes: list, connections: dict) -> dict[str, Any]:
    """Standard workflow envelope without read-only fields."""
    return {
        "name": name,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
    }


def build_webhook_receiver(webhook_path: str = "video-callback") -> dict[str, Any]:
    """WF-HELPER: receives callback from video API."""
    trigger = webhook_trigger(webhook_path, (240, 300))
    route = {
        "id": _id(), "name": "Route by Event",
        "type": "n8n-nodes-base.switch",
        "typeVersion": 3, "position": [460, 300],
        "parameters": {
            "mode": "expression",
            "output": '={{ $json.event }}',
            "rules": {"rules": [
                {"value": "job.completed"},
                {"value": "job.failed"},
                {"value": "job.cancelled"},
            ]},
        },
    }
    ok_set = set_node("Completed", [
        {"id": _id(), "name": "status",  "value": "done",                                      "type": "string"},
        {"id": _id(), "name": "job_id",  "value": '={{ $json.job_id }}',                       "type": "string"},
        {"id": _id(), "name": "output",  "value": '={{ ($json.metadata || {}).result_items }}', "type": "string"},
    ], (680, 200))
    fail_set = set_node("Failed", [
        {"id": _id(), "name": "status", "value": "failed",                              "type": "string"},
        {"id": _id(), "name": "error",  "value": '={{ ($json.error_detail || {}).message }}', "type": "string"},
    ], (680, 360))
    cancel_set = set_node("Cancelled", [
        {"id": _id(), "name": "status", "value": "cancelled", "type": "string"},
    ], (680, 520))

    nodes = [trigger, route, ok_set, fail_set, cancel_set]
    connections = {
        trigger["name"]: {"main": [[{"node": route["name"], "type": "main", "index": 0}]]},
        route["name"]:   {"main": [
            [{"node": ok_set["name"],     "type": "main", "index": 0}],
            [{"node": fail_set["name"],   "type": "main", "index": 0}],
            [{"node": cancel_set["name"], "type": "main", "index": 0}],
        ]},
    }
    return {
        "name": "WF-HELPER — Webhook Receiver",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
    }


def build_batch_workflow(
    video_api_url: str,
    video_api_key: str,
) -> dict[str, Any]:
    """WF-17: Create 4 jobs in parallel and track all."""
    trigger = manual_trigger((240, 300))
    code_create = code_node("Create 4 Jobs", f"""
const baseUrl = '{video_api_url}';
const apiKey = '{video_api_key}';
const configs = [
  {{name:'batch-1', duration:3}},
  {{name:'batch-2', duration:4}},
  {{name:'batch-3', duration:5}},
  {{name:'batch-4', duration:6}},
];
const results = [];
for (const cfg of configs) {{
  const resp = await $http.request({{
    method:'POST', url:`${{baseUrl}}/jobs`,
    headers:{{'X-API-Key': apiKey, 'Content-Type':'application/json'}},
    body: JSON.stringify({{
      pipeline_type:'low_level',
      input_path:'test_input.mp4',
      payload:{{
        output_name:`n8n-${{cfg.name}}`,
        operations:[{{type:'cut', params:{{start:0, duration:cfg.duration}}}}]
      }}
    }})
  }});
  results.push({{job_id: resp.id, name: cfg.name}});
}}
return results.map(r => ({{json: r}}));
""", (460, 300))

    poll_all = code_node("Poll All Until Done", f"""
const baseUrl = '{video_api_url}';
const apiKey = '{video_api_key}';
const jobIds = $input.all().map(i => i.json.job_id);
const terminal = new Set(['done','failed','cancelled']);
const deadline = Date.now() + 300000;
while (Date.now() < deadline) {{
  const statuses = await Promise.all(jobIds.map(async id => {{
    const r = await $http.request({{
      method:'GET', url:`${{baseUrl}}/jobs/${{id}}`,
      headers:{{'X-API-Key': apiKey}}
    }});
    return {{id, status: r.status, output: r.output_path}};
  }}));
  if (statuses.every(s => terminal.has(s.status))) {{
    const passed = statuses.filter(s => s.status === 'done').length;
    return [{{json: {{total: statuses.length, passed, failed: statuses.length-passed, statuses}}}}];
  }}
  await new Promise(r => setTimeout(r, 3000));
}}
throw new Error('Timeout waiting for all jobs');
""", (680, 300))

    nodes = [trigger, code_create, poll_all]
    connections = {
        trigger["name"]:     {"main": [[{"node": code_create["name"], "type": "main", "index": 0}]]},
        code_create["name"]: {"main": [[{"node": poll_all["name"],    "type": "main", "index": 0}]]},
    }
    return {
        "name": "WF-17 — Batch 4 Videos Song Song",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
    }


# ---------------------------------------------------------------------------
# All workflow definitions
# ---------------------------------------------------------------------------

def all_workflows(video_api_url: str, video_api_key: str) -> list[dict[str, Any]]:
    vurl = video_api_url
    vkey = video_api_key
    wfs = []

    # WF-HELPER
    wfs.append(build_webhook_receiver("video-callback"))

    # WF-01 Cut + Speed + Flip
    wfs.append(build_simple_poll_workflow(
        "WF-01 — Cut + Speed + Flip", vurl, vkey,
        {"pipeline_type": "low_level", "input_path": "test_input.mp4", "payload": {
            "output_name": "n8n-wf01",
            "operations": [
                {"type": "cut",   "params": {"start": 0, "duration": 5}},
                {"type": "speed", "params": {"factor": 1.2}},
                {"type": "flip",  "params": {"mode": "horizontal"}},
            ],
        }},
    ))

    # WF-02 Portrait
    wfs.append(build_simple_poll_workflow(
        "WF-02 — Portrait Reframe 1080x1920", vurl, vkey,
        {"pipeline_type": "low_level", "input_path": "test_input.mp4", "payload": {
            "output_name": "n8n-wf02-portrait",
            "operations": [
                {"type": "blur_bg_portrait", "params": {"output_width": 1080, "output_height": 1920}},
                {"type": "pad_border",       "params": {"size": 10, "color": "#000000"}},
                {"type": "auto_zoom",        "params": {"interval_seconds": 5}},
            ],
        }},
    ))

    # WF-03 HStack
    wfs.append(build_simple_poll_workflow(
        "WF-03 — Split Screen HStack 1280x720", vurl, vkey,
        {"pipeline_type": "low_level", "input_path": "test.mp4", "payload": {
            "output_name": "n8n-wf03-hstack",
            "operations": [{"type": "hstack", "params": {
                "second_video": "test_input.mp4",
                "layout": "horizontal",
                "output_width": 1280,
                "output_height": 720,
            }}],
        }},
    ))

    # WF-04 TikTok Split
    wfs.append(build_simple_poll_workflow(
        "WF-04 — TikTok Split Screen", vurl, vkey,
        {"pipeline_type": "low_level", "input_path": "test.mp4", "payload": {
            "output_name": "n8n-wf04-tiktok",
            "operations": [{"type": "split_screen", "params": {
                "b_roll_video": "test_input.mp4",
                "split_ratio": 0.5,
                "audio_source": "mix",
            }}],
        }},
    ))

    # WF-05 Audio
    wfs.append(build_simple_poll_workflow(
        "WF-05 — Audio Operations", vurl, vkey,
        {"pipeline_type": "low_level", "input_path": "test_input.mp4", "payload": {
            "output_name": "n8n-wf05-audio",
            "operations": [
                {"type": "audio_pitch",     "params": {"semitones": 2, "preserve_tempo": True}},
                {"type": "audio_normalize", "params": {}},
                {"type": "audio_fade",      "params": {"type": "in", "duration": 0.5}},
            ],
        }},
    ))

    # WF-06 Dubbing
    wfs.append(build_simple_poll_workflow(
        "WF-06 — Dubbing EN→VI", vurl, vkey,
        {"pipeline_type": "dubbing", "input_path": "test_input.mp4", "payload": {
            "source_language": "en",
            "target_language": "vi",
            "translator_service": "google",
            "tts_voice": "vi-VN-HoaiMyNeural",
            "tts_rate": "-5%",
        }},
    ))

    # WF-07 Subtitle
    wfs.append(build_simple_poll_workflow(
        "WF-07 — Subtitle Generation", vurl, vkey,
        {"pipeline_type": "subtitle", "input_path": "test_input.mp4", "payload": {
            "language": "auto",
            "burn_subtitle": True,
            "font_size": 28,
        }},
    ))

    # WF-08 Silence Cut
    wfs.append(build_simple_poll_workflow(
        "WF-08 — Silence Cut", vurl, vkey,
        {"pipeline_type": "silence_cut", "input_path": "test_input.mp4", "payload": {
            "min_silence_duration": 0.3,
            "silence_threshold_db": -35,
        }},
    ))

    # WF-09 Audio Extract
    wfs.append(build_simple_poll_workflow(
        "WF-09 — Audio Extract", vurl, vkey,
        {"pipeline_type": "audio-extract", "input_path": "test_input.mp4", "payload": {
            "format": "wav",
        }},
    ))

    # WF-10 Ad Video
    wfs.append(build_simple_poll_workflow(
        "WF-10 — Ad Video TTS", vurl, vkey,
        {"pipeline_type": "ad_video", "input_path": "test.mp4", "payload": {
            "ad_text": "Sản phẩm chất lượng cao, đặt hàng ngay hôm nay!",
            "tts_voice": "vi-VN-HoaiMyNeural",
            "tts_engine": "edge-tts",
            "burn_subtitle": True,
        }},
    ))

    # WF-11 Auto B-Roll
    wfs.append(build_simple_poll_workflow(
        "WF-11 — Auto B-Roll", vurl, vkey,
        {"pipeline_type": "auto_broll", "input_path": "test.mp4", "payload": {
            "broll_source": "test_input.mp4",
        }},
    ))

    # WF-12 Face Track
    wfs.append(build_simple_poll_workflow(
        "WF-12 — Face Track Portrait", vurl, vkey,
        {"pipeline_type": "face_track_portrait", "input_path": "test_input.mp4", "payload": {
            "output_width": 1080,
            "output_height": 1920,
        }},
    ))

    # WF-13 Semantic Edit
    wfs.append(build_simple_poll_workflow(
        "WF-13 — Semantic Edit Silence Cut", vurl, vkey,
        {"pipeline_type": "semantic_edit", "input_path": "test_input.mp4", "payload": {
            "command": "silence_cut",
            "min_silence_duration": 0.3,
            "silence_threshold_db": -35,
        }},
    ))

    # WF-14 Split Video
    wfs.append(build_simple_poll_workflow(
        "WF-14 — Split Video Chunks", vurl, vkey,
        {"pipeline_type": "split_video", "input_path": "test.mp4", "payload": {
            "segment_duration": 30,
        }},
    ))

    # WF-15 Extract Frames
    wfs.append(build_simple_poll_workflow(
        "WF-15 — Extract Frames", vurl, vkey,
        {"pipeline_type": "extract_frames", "input_path": "test_input.mp4", "payload": {
            "fps": 1,
            "format": "jpg",
            "max_frames": 10,
        }},
    ))

    # WF-16 Workflow DAG
    wfs.append(build_simple_poll_workflow(
        "WF-16 — Workflow DAG Multi-step", vurl, vkey,
        {"pipeline_type": "workflow", "input_path": "test_input.mp4", "payload": {
            "workflow": {"nodes": {
                "cut":    {"type": "video.cut",       "params": {"start": 0, "end": 15}},
                "scale":  {"type": "video.scale",     "params": {"width": 1080, "height": 1920}, "depends_on": ["cut"]},
                "border": {"type": "video.pad_border","params": {"size": 10, "color": "white"}, "depends_on": ["scale"]},
                "export": {"type": "media.finalize",  "depends_on": ["border"]},
            }},
        }},
    ))

    # WF-17 Batch
    wfs.append(build_batch_workflow(vurl, vkey))

    return wfs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-create n8n workflow test suite for AI Video Engine.")
    parser.add_argument("--n8n-url", default="http://localhost:5678")
    parser.add_argument("--n8n-api-key", required=True, help="n8n API key (Settings → API)")
    parser.add_argument("--video-api-url", default="http://localhost:6666")
    parser.add_argument("--video-api-key", default="", help="Video Engine API key")
    parser.add_argument("--dry-run", action="store_true", help="Print JSON, do not upload")
    args = parser.parse_args()

    workflows = all_workflows(args.video_api_url, args.video_api_key)

    if args.dry_run:
        print(json.dumps(workflows, ensure_ascii=False, indent=2))
        return 0

    print(f"Creating {len(workflows)} workflows on {args.n8n_url} ...")
    created: list[str] = []
    errors: list[str] = []
    for wf in workflows:
        try:
            wf_id = create_workflow(args.n8n_url, args.n8n_api_key, wf)
            print(f"  [OK] [{wf_id}] {wf['name']}")
            created.append(wf_id)
        except RuntimeError as exc:
            print(f"  [FAIL] {wf['name']}: {exc}", file=sys.stderr)
            errors.append(str(exc))

    print(f"\nDone: {len(created)} created, {len(errors)} errors.")
    if errors:
        return 1
    print(f"\nOpen n8n → http://localhost:5678 to activate and run each workflow.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
