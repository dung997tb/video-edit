"""
setup_n8n_workflows.py
Create an n8n workflow test suite for AI Video Engine.

Usage:
    python scripts/setup_n8n_workflows.py \
        --n8n-url http://localhost:5678 \
        --n8n-api-key YOUR_N8N_API_KEY \
        --video-api-url http://host.docker.internal:6666 \
        --video-api-key YOUR_VIDEO_API_KEY
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


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


def activate_workflow(n8n_url: str, api_key: str, workflow_id: str) -> dict[str, Any]:
    return n8n_request("POST", n8n_url, f"/api/v1/workflows/{workflow_id}/activate", api_key, {})


def deactivate_workflow(n8n_url: str, api_key: str, workflow_id: str) -> dict[str, Any]:
    return n8n_request("POST", n8n_url, f"/api/v1/workflows/{workflow_id}/deactivate", api_key, {})


def delete_workflow(n8n_url: str, api_key: str, workflow_id: str) -> dict[str, Any]:
    return n8n_request("DELETE", n8n_url, f"/api/v1/workflows/{workflow_id}", api_key)


def list_executions(
    n8n_url: str,
    api_key: str,
    *,
    workflow_id: str | None = None,
    limit: int = 100,
    include_data: bool = False,
) -> dict[str, Any]:
    query: dict[str, Any] = {"limit": limit}
    if workflow_id:
        query["workflowId"] = workflow_id
    if include_data:
        query["includeData"] = "true"
    path = f"/api/v1/executions?{urlencode(query)}"
    return n8n_request("GET", n8n_url, path, api_key)


def get_execution(n8n_url: str, api_key: str, execution_id: str | int, *, include_data: bool = True) -> dict[str, Any]:
    suffix = "?includeData=true" if include_data else ""
    return n8n_request("GET", n8n_url, f"/api/v1/executions/{execution_id}{suffix}", api_key)


def _id() -> str:
    return str(uuid.uuid4())


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return normalized or "workflow"


def manual_trigger(pos: tuple[int, int] = (240, 300)) -> dict[str, Any]:
    return {
        "id": _id(),
        "name": "Manual Trigger",
        "type": "n8n-nodes-base.manualTrigger",
        "typeVersion": 1,
        "position": list(pos),
        "parameters": {},
    }


def webhook_trigger(path: str, pos: tuple[int, int] = (240, 300)) -> dict[str, Any]:
    return {
        "id": _id(),
        "name": "Webhook Trigger",
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


def code_node(name: str, code: str, pos: tuple[int, int]) -> dict[str, Any]:
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
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4,
        "position": list(pos),
        "parameters": {
            "method": "POST",
            "url": f"{video_api_url.rstrip('/')}/jobs",
            "sendHeaders": True,
            "headerParameters": {"parameters": headers},
            "sendBody": True,
            "contentType": "raw",
            "rawContentType": "application/json",
            "body": json.dumps(body, ensure_ascii=False),
        },
    }


def trigger_node(trigger_mode: str, name: str, webhook_prefix: str) -> dict[str, Any]:
    if trigger_mode == "webhook":
        return webhook_trigger(f"{webhook_prefix}-{slugify(name)}")
    return manual_trigger()


def build_job_lifecycle_code(
    video_api_url: str,
    video_api_key: str,
    job_body: dict[str, Any],
    *,
    timeout_seconds: int = 300,
    poll_seconds: int = 3,
) -> str:
    body_json = json.dumps(job_body, ensure_ascii=False)
    url_json = json.dumps(video_api_url.rstrip("/"), ensure_ascii=False)
    key_json = json.dumps(video_api_key, ensure_ascii=False)
    return f"""
const baseUrl = {url_json};
const apiKey = {key_json};
const jobBody = {body_json};
const timeoutSeconds = {timeout_seconds};
const pollSeconds = {poll_seconds};
const terminal = new Set(['done', 'failed', 'cancelled']);

const headers = {{ 'Content-Type': 'application/json' }};
if (apiKey) {{
  headers['X-API-Key'] = apiKey;
}}

async function requestJson(method, url, body) {{
  const response = await fetch(url, {{
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  }});
  const text = await response.text();
  let payload = {{}};
  if (text) {{
    payload = JSON.parse(text);
  }}
  if (!response.ok) {{
    throw new Error(`${{method}} ${{url}} failed: HTTP ${{response.status}} ${{text}}`);
  }}
  return payload;
}}

const createResponse = await requestJson('POST', `${{baseUrl}}/jobs`, jobBody);

const jobId = createResponse.id;
if (!jobId) {{
  throw new Error(`Create job response missing id: ${{JSON.stringify(createResponse)}}`);
}}

let job = createResponse;
const deadline = Date.now() + timeoutSeconds * 1000;
while (!terminal.has(job.status)) {{
  if (Date.now() >= deadline) {{
    throw new Error(`Timeout waiting for job ${{jobId}}; last status=${{job.status}}`);
  }}
  await new Promise(resolve => setTimeout(resolve, pollSeconds * 1000));
  job = await requestJson('GET', `${{baseUrl}}/jobs/${{jobId}}`);
}}

return [{{
  json: {{
    ...job,
    job_id: job.id || jobId,
    result_items: ((job.metadata || {{}}).result_items || []),
    create_response: createResponse,
  }},
}}];
"""


def build_batch_poll_code(video_api_url: str, video_api_key: str) -> str:
    url_json = json.dumps(video_api_url.rstrip("/"), ensure_ascii=False)
    key_json = json.dumps(video_api_key, ensure_ascii=False)
    return f"""
const baseUrl = {url_json};
const apiKey = {key_json};
const headers = {{ 'Content-Type': 'application/json' }};
if (apiKey) {{
  headers['X-API-Key'] = apiKey;
}}
async function requestJson(method, url, body) {{
  const response = await fetch(url, {{
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  }});
  const text = await response.text();
  let payload = {{}};
  if (text) {{
    payload = JSON.parse(text);
  }}
  if (!response.ok) {{
    throw new Error(`${{method}} ${{url}} failed: HTTP ${{response.status}} ${{text}}`);
  }}
  return payload;
}}
const configs = [
  {{ name: 'batch-1', duration: 3 }},
  {{ name: 'batch-2', duration: 4 }},
  {{ name: 'batch-3', duration: 5 }},
  {{ name: 'batch-4', duration: 6 }},
];
const created = [];
for (const cfg of configs) {{
  const response = await requestJson('POST', `${{baseUrl}}/jobs`, {{
      pipeline_type: 'low_level',
      input_path: 'test_input.mp4',
      payload: {{
        output_name: `n8n-${{cfg.name}}`,
        operations: [{{ type: 'cut', params: {{ start: 0, duration: cfg.duration }} }}],
      }},
  }});
  created.push(response.id);
}}
const terminal = new Set(['done', 'failed', 'cancelled']);
const deadline = Date.now() + 300000;
while (Date.now() < deadline) {{
  const jobs = await Promise.all(created.map(async jobId => await requestJson('GET', `${{baseUrl}}/jobs/${{jobId}}`)));
  if (jobs.every(job => terminal.has(job.status))) {{
    return [{{
      json: {{
        total: jobs.length,
        passed: jobs.filter(job => job.status === 'done').length,
        failed: jobs.filter(job => job.status !== 'done').length,
        statuses: jobs.map(job => ({{
          job_id: job.id,
          status: job.status,
          output_path: job.output_path || null,
        }})),
      }},
    }}];
  }}
  await new Promise(resolve => setTimeout(resolve, 3000));
}}
throw new Error(`Timeout waiting for batch jobs: ${{created.join(', ')}}`);
"""


def build_webhook_receiver_code() -> str:
    return """
const input = $input.first().json;
const payload = input.body || input;
const metadata = payload.metadata || {};
return [{
  json: {
    event: payload.event || null,
    status: payload.status || null,
    job_id: payload.job_id || null,
    output_path: payload.output_path || null,
    result_items: metadata.result_items || [],
    error: (payload.error_detail || {}).message || payload.error || null,
  },
}];
"""


def build_simple_poll_workflow(
    name: str,
    video_api_url: str,
    video_api_key: str,
    job_body: dict[str, Any],
    *,
    trigger_mode: str = "manual",
    webhook_prefix: str = "video-suite",
    timeout_seconds: int = 300,
    poll_seconds: int = 3,
) -> dict[str, Any]:
    trigger = trigger_node(trigger_mode, name, webhook_prefix)
    run_job = http_post_job("Create Job", video_api_url, video_api_key, job_body, (540, 300))
    return {
        "name": name,
        "nodes": [trigger, run_job],
        "connections": {
            trigger["name"]: {
                "main": [[{"node": run_job["name"], "type": "main", "index": 0}]],
            },
        },
        "settings": {"executionOrder": "v1"},
    }


def _credential_ref(credential_id: str, credential_name: str) -> dict[str, Any]:
    return {
        "aiVideoEngineApi": {
            "id": credential_id,
            "name": credential_name,
        },
    }


def custom_node_create_job(
    name: str,
    credential_id: str,
    pipeline_type: str,
    source_value: str,
    payload: dict[str, Any],
    *,
    source_mode: str = "inputUri",
    credential_name: str = "AI Video Engine API",
    pos: tuple[int, int] = (520, 300),
) -> dict[str, Any]:
    if source_mode not in {"inputUri", "sourceKey"}:
        raise ValueError(f"unsupported source_mode: {source_mode}")
    return {
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-ai-video-engine.aiVideoEngine",
        "typeVersion": 1,
        "position": list(pos),
        "credentials": _credential_ref(credential_id, credential_name),
        "parameters": {
            "resource": "job",
            "jobOperation": "createCustom",
            "sourceMode": source_mode,
            "inputUri": source_value if source_mode == "inputUri" else "",
            "sourceKey": source_value if source_mode == "sourceKey" else "",
            "pipelineType": pipeline_type,
            "payloadJson": json.dumps(payload, ensure_ascii=False),
            "metadataJson": "{}",
            "advancedPayloadJson": "{}",
            "priority": 0,
            "outputMode": "job",
        },
    }


def custom_node_wait_job(
    name: str,
    credential_id: str,
    *,
    credential_name: str = "AI Video Engine API",
    job_id_expression: str = "={{ $json.job_id }}",
    pos: tuple[int, int] = (760, 300),
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    return {
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-ai-video-engine.aiVideoEngine",
        "typeVersion": 1,
        "position": list(pos),
        "credentials": _credential_ref(credential_id, credential_name),
        "parameters": {
            "resource": "job",
            "jobOperation": "wait",
            "jobId": job_id_expression,
            "intervalSeconds": 5,
            "timeoutSeconds": timeout_seconds,
            "failOnTerminalError": True,
            "outputMode": "job",
        },
    }


def custom_node_cancel_job(
    name: str,
    credential_id: str,
    *,
    credential_name: str = "AI Video Engine API",
    pos: tuple[int, int] = (760, 300),
) -> dict[str, Any]:
    return {
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-ai-video-engine.aiVideoEngine",
        "typeVersion": 1,
        "position": list(pos),
        "credentials": _credential_ref(credential_id, credential_name),
        "parameters": {
            "resource": "job",
            "jobOperation": "cancel",
            "jobId": "={{ $json.job_id }}",
            "outputMode": "job",
        },
    }


def custom_node_get_job(
    name: str,
    credential_id: str,
    *,
    credential_name: str = "AI Video Engine API",
    pos: tuple[int, int] = (980, 300),
) -> dict[str, Any]:
    return {
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-ai-video-engine.aiVideoEngine",
        "typeVersion": 1,
        "position": list(pos),
        "credentials": _credential_ref(credential_id, credential_name),
        "parameters": {
            "resource": "job",
            "jobOperation": "get",
            "jobId": "={{ $json.job_id }}",
            "outputMode": "job",
        },
    }


def custom_node_list_jobs(
    name: str,
    credential_id: str,
    *,
    credential_name: str = "AI Video Engine API",
    pos: tuple[int, int] = (1200, 300),
) -> dict[str, Any]:
    return {
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-ai-video-engine.aiVideoEngine",
        "typeVersion": 1,
        "position": list(pos),
        "credentials": _credential_ref(credential_id, credential_name),
        "parameters": {
            "resource": "job",
            "jobOperation": "list",
            "status": "",
            "limit": 20,
            "outputMode": "job",
        },
    }


def custom_node_preset_job(
    name: str,
    credential_id: str,
    preset_operation: str,
    source_value: str,
    parameters: dict[str, Any],
    *,
    source_mode: str = "inputUri",
    credential_name: str = "AI Video Engine API",
    pos: tuple[int, int] = (520, 300),
) -> dict[str, Any]:
    if source_mode not in {"inputUri", "sourceKey"}:
        raise ValueError(f"unsupported source_mode: {source_mode}")
    base_parameters: dict[str, Any] = {
        "resource": "preset",
        "presetOperation": preset_operation,
        "sourceMode": source_mode,
        "inputUri": source_value if source_mode == "inputUri" else "",
        "sourceKey": source_value if source_mode == "sourceKey" else "",
        "webhookUrl": "",
        "outputName": "",
        "metadataJson": "{}",
        "advancedPayloadJson": "{}",
        "priority": 0,
        "outputMode": "job",
    }
    base_parameters.update(parameters)
    return {
        "id": _id(),
        "name": name,
        "type": "n8n-nodes-ai-video-engine.aiVideoEngine",
        "typeVersion": 1,
        "position": list(pos),
        "credentials": _credential_ref(credential_id, credential_name),
        "parameters": base_parameters,
    }


def custom_node_trigger(path: str, pos: tuple[int, int] = (240, 300)) -> dict[str, Any]:
    return {
        "id": _id(),
        "name": "AI Video Callback",
        "type": "n8n-nodes-ai-video-engine.aiVideoEngineTrigger",
        "typeVersion": 1,
        "position": list(pos),
        "webhookId": _id(),
        "parameters": {
            "path": path,
            "events": ["job.completed", "job.failed", "job.cancelled"],
        },
    }


def build_custom_create_wait_workflow(
    name: str,
    credential_id: str,
    source_value: str,
    *,
    source_mode: str = "inputUri",
    credential_name: str = "AI Video Engine API",
    trigger_mode: str = "webhook",
    webhook_prefix: str = "video-suite",
) -> dict[str, Any]:
    trigger = trigger_node(trigger_mode, name, webhook_prefix)
    create = custom_node_create_job(
        "Create Job",
        credential_id,
        "low_level",
        source_value,
        {
            "output_name": "cn-01-cut-5s",
            "operations": [{"type": "cut", "params": {"start": 0, "duration": 5}}],
        },
        source_mode=source_mode,
        credential_name=credential_name,
    )
    wait = custom_node_wait_job("Wait Job", credential_id, credential_name=credential_name)
    return {
        "name": name,
        "nodes": [trigger, create, wait],
        "connections": {
            trigger["name"]: {"main": [[{"node": create["name"], "type": "main", "index": 0}]]},
            create["name"]: {"main": [[{"node": wait["name"], "type": "main", "index": 0}]]},
        },
        "settings": {"executionOrder": "v1"},
    }


def build_custom_preset_wait_workflow(
    name: str,
    credential_id: str,
    source_value: str,
    preset_operation: str,
    parameters: dict[str, Any],
    *,
    source_mode: str = "inputUri",
    credential_name: str = "AI Video Engine API",
    trigger_mode: str = "webhook",
    webhook_prefix: str = "video-suite",
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    trigger = trigger_node(trigger_mode, name, webhook_prefix)
    create = custom_node_preset_job(
        "Create Preset Job",
        credential_id,
        preset_operation,
        source_value,
        parameters,
        source_mode=source_mode,
        credential_name=credential_name,
    )
    wait = custom_node_wait_job(
        "Wait Job",
        credential_id,
        credential_name=credential_name,
        timeout_seconds=timeout_seconds,
    )
    return {
        "name": name,
        "nodes": [trigger, create, wait],
        "connections": {
            trigger["name"]: {"main": [[{"node": create["name"], "type": "main", "index": 0}]]},
            create["name"]: {"main": [[{"node": wait["name"], "type": "main", "index": 0}]]},
        },
        "settings": {"executionOrder": "v1"},
    }


def build_custom_trigger_receiver(webhook_path: str) -> dict[str, Any]:
    trigger = custom_node_trigger(webhook_path, (240, 300))
    normalize = code_node("Normalize Event", build_webhook_receiver_code(), (520, 300))
    return {
        "name": "CN-05 — Trigger Callback",
        "nodes": [trigger, normalize],
        "connections": {
            trigger["name"]: {"main": [[{"node": normalize["name"], "type": "main", "index": 0}]]},
        },
        "settings": {"executionOrder": "v1"},
    }


def build_custom_cancel_workflow(
    credential_id: str,
    source_value: str,
    *,
    source_mode: str = "inputUri",
    credential_name: str = "AI Video Engine API",
    trigger_mode: str = "webhook",
    webhook_prefix: str = "video-suite",
) -> dict[str, Any]:
    name = "CN-06 — Cancel Flow"
    trigger = trigger_node(trigger_mode, name, webhook_prefix)
    create = custom_node_create_job(
        "Create Job",
        credential_id,
        "low_level",
        source_value,
        {
            "output_name": "cn-06-cancel",
            "operations": [
                {"type": "blur_bg_portrait", "params": {"output_width": 1080, "output_height": 1920}},
                {"type": "auto_zoom", "params": {"interval_seconds": 5}},
                {"type": "pad_border", "params": {"size": 10, "color": "#000000"}},
            ],
        },
        source_mode=source_mode,
        credential_name=credential_name,
    )
    cancel = custom_node_cancel_job("Cancel Job", credential_id, credential_name=credential_name)
    return {
        "name": name,
        "nodes": [trigger, create, cancel],
        "connections": {
            trigger["name"]: {"main": [[{"node": create["name"], "type": "main", "index": 0}]]},
            create["name"]: {"main": [[{"node": cancel["name"], "type": "main", "index": 0}]]},
        },
        "settings": {"executionOrder": "v1"},
    }


def build_custom_get_list_workflow(
    credential_id: str,
    source_value: str,
    *,
    source_mode: str = "inputUri",
    credential_name: str = "AI Video Engine API",
    trigger_mode: str = "webhook",
    webhook_prefix: str = "video-suite",
) -> dict[str, Any]:
    name = "CN-07 — Get + List"
    trigger = trigger_node(trigger_mode, name, webhook_prefix)
    create = custom_node_create_job(
        "Create Job",
        credential_id,
        "low_level",
        source_value,
        {
            "output_name": "cn-07-get-list",
            "operations": [{"type": "cut", "params": {"start": 0, "duration": 3}}],
        },
        source_mode=source_mode,
        credential_name=credential_name,
    )
    wait = custom_node_wait_job("Wait Job", credential_id, credential_name=credential_name, timeout_seconds=300)
    get = custom_node_get_job("Get Job", credential_id, credential_name=credential_name)
    list_jobs = custom_node_list_jobs("List Jobs", credential_id, credential_name=credential_name)
    return {
        "name": name,
        "nodes": [trigger, create, wait, get, list_jobs],
        "connections": {
            trigger["name"]: {"main": [[{"node": create["name"], "type": "main", "index": 0}]]},
            create["name"]: {"main": [[{"node": wait["name"], "type": "main", "index": 0}]]},
            wait["name"]: {"main": [[{"node": get["name"], "type": "main", "index": 0}]]},
            get["name"]: {"main": [[{"node": list_jobs["name"], "type": "main", "index": 0}]]},
        },
        "settings": {"executionOrder": "v1"},
    }


def build_custom_batch_workflow(
    credential_id: str,
    source_value: str,
    *,
    source_mode: str = "inputUri",
    credential_name: str = "AI Video Engine API",
    trigger_mode: str = "webhook",
    webhook_prefix: str = "video-suite",
) -> dict[str, Any]:
    name = "CN-08 — Batch 4 Jobs"
    trigger = trigger_node(trigger_mode, name, webhook_prefix)
    build_items = code_node(
        "Build Batch Items",
        f"""
const sourceValue = {json.dumps(source_value, ensure_ascii=False)};
return [3, 4, 5, 6].map((duration, index) => ({{
  json: {{
    pipeline_type: 'low_level',
    source_value: sourceValue,
    payload: {{
      output_name: `cn-08-batch-${{index + 1}}`,
      operations: [{{ type: 'cut', params: {{ start: 0, duration }} }}],
    }},
  }},
}}));
""",
        (500, 300),
    )
    create = custom_node_create_job(
        "Create Job",
        credential_id,
        "={{ $json.pipeline_type }}",
        "={{ $json.source_value }}",
        {},
        source_mode=source_mode,
        credential_name=credential_name,
        pos=(760, 300),
    )
    create["parameters"]["payloadJson"] = "={{ JSON.stringify($json.payload) }}"
    wait = custom_node_wait_job("Wait Job", credential_id, credential_name=credential_name, pos=(1000, 300))
    return {
        "name": name,
        "nodes": [trigger, build_items, create, wait],
        "connections": {
            trigger["name"]: {"main": [[{"node": build_items["name"], "type": "main", "index": 0}]]},
            build_items["name"]: {"main": [[{"node": create["name"], "type": "main", "index": 0}]]},
            create["name"]: {"main": [[{"node": wait["name"], "type": "main", "index": 0}]]},
        },
        "settings": {"executionOrder": "v1"},
    }


def build_webhook_receiver(
    webhook_path: str = "video-callback",
    *,
    trigger_mode: str = "webhook",
) -> dict[str, Any]:
    if trigger_mode != "webhook":
        raise ValueError("Webhook receiver only supports webhook trigger mode")
    trigger = webhook_trigger(webhook_path, (240, 300))
    normalize = code_node("Normalize Event", build_webhook_receiver_code(), (520, 300))
    return {
        "name": "WF-HELPER — Webhook Receiver",
        "nodes": [trigger, normalize],
        "connections": {
            trigger["name"]: {
                "main": [[{"node": normalize["name"], "type": "main", "index": 0}]],
            },
        },
        "settings": {"executionOrder": "v1"},
    }


def build_batch_workflow(
    video_api_url: str,
    video_api_key: str,
    *,
    trigger_mode: str = "manual",
    webhook_prefix: str = "video-suite",
) -> dict[str, Any]:
    name = "WF-17 — Batch 4 Videos Song Song"
    trigger = trigger_node(trigger_mode, name, webhook_prefix)
    batch = code_node("Run Batch Jobs", build_batch_poll_code(video_api_url, video_api_key), (540, 300))
    return {
        "name": name,
        "nodes": [trigger, batch],
        "connections": {
            trigger["name"]: {
                "main": [[{"node": batch["name"], "type": "main", "index": 0}]],
            },
        },
        "settings": {"executionOrder": "v1"},
    }


def workflow_webhook_path(workflow: dict[str, Any]) -> str | None:
    for node in workflow.get("nodes", []):
        if node.get("type") in {"n8n-nodes-base.webhook", "n8n-nodes-ai-video-engine.aiVideoEngineTrigger"}:
            return str((node.get("parameters") or {}).get("path") or "")
    return None


def all_custom_node_workflows(
    source_value: str,
    credential_id: str,
    *,
    source_mode: str = "inputUri",
    credential_name: str = "AI Video Engine API",
    trigger_mode: str = "manual",
    webhook_prefix: str = "video-suite",
) -> list[dict[str, Any]]:
    workflows = [
        build_custom_create_wait_workflow(
            "CN-01 — Smoke Cut 5s",
            credential_id,
            source_value,
            source_mode=source_mode,
            credential_name=credential_name,
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
        ),
        build_custom_preset_wait_workflow(
            "CN-02 — Preset Low Level Cut+Portrait 1080x1920",
            credential_id,
            source_value,
            "lowLevel",
            {
                "operationTemplate": "customJson",
                "operationsJson": json.dumps(
                    {
                        "operations": [
                            {"type": "cut", "params": {"start": 0, "duration": 5}},
                            {
                                "type": "blur_bg_portrait",
                                "params": {"output_width": 1080, "output_height": 1920},
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                "outputName": "cn-02-lowlevel-cut-scale",
            },
            source_mode=source_mode,
            credential_name=credential_name,
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
        ),
        build_custom_preset_wait_workflow(
            "CN-03 — Preset Dubbing VI",
            credential_id,
            source_value,
            "dubbing",
            {
                "sourceLanguage": "auto",
                "targetLanguage": "vi",
                "translatorService": "google",
                "ttsVoice": "vi-VN-HoaiMyNeural",
                "ttsRate": "-5%",
                "outputName": "cn-03-dubbing-vi",
            },
            source_mode=source_mode,
            credential_name=credential_name,
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=900,
        ),
        build_custom_preset_wait_workflow(
            "CN-04 — Preset Subtitle Burn",
            credential_id,
            source_value,
            "subtitle",
            {
                "subtitleLanguage": "auto",
                "burnSubtitle": True,
                "fontSize": 28,
                "fontColor": "white",
                "strokeColor": "black",
                "strokeWidth": 2,
                "outputName": "cn-04-subtitle-burn",
            },
            source_mode=source_mode,
            credential_name=credential_name,
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=900,
        ),
        build_custom_trigger_receiver(f"{webhook_prefix}-custom-trigger"),
        build_custom_cancel_workflow(
            credential_id,
            source_value,
            source_mode=source_mode,
            credential_name=credential_name,
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
        ),
        build_custom_get_list_workflow(
            credential_id,
            source_value,
            source_mode=source_mode,
            credential_name=credential_name,
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
        ),
        build_custom_batch_workflow(
            credential_id,
            source_value,
            source_mode=source_mode,
            credential_name=credential_name,
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
        ),
    ]
    return workflows


def all_workflows(
    video_api_url: str,
    video_api_key: str,
    *,
    trigger_mode: str = "manual",
    webhook_prefix: str = "video-suite",
) -> list[dict[str, Any]]:
    workflows: list[dict[str, Any]] = []
    if trigger_mode == "webhook":
        workflows.append(build_webhook_receiver(f"{webhook_prefix}-callback", trigger_mode=trigger_mode))

    workflows.append(
        build_simple_poll_workflow(
            "WF-01 — Cut + Speed + Flip",
            video_api_url,
            video_api_key,
            {
                "pipeline_type": "low_level",
                "input_path": "test_input.mp4",
                "payload": {
                    "output_name": "n8n-wf01",
                    "operations": [
                        {"type": "cut", "params": {"start": 0, "duration": 5}},
                        {"type": "speed", "params": {"factor": 1.2}},
                        {"type": "flip", "params": {"mode": "horizontal"}},
                    ],
                },
            },
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=240,
        )
    )
    workflows.append(
        build_simple_poll_workflow(
            "WF-02 — Portrait Reframe 1080x1920",
            video_api_url,
            video_api_key,
            {
                "pipeline_type": "low_level",
                "input_path": "test_input.mp4",
                "payload": {
                    "output_name": "n8n-wf02-portrait",
                    "operations": [
                        {"type": "blur_bg_portrait", "params": {"output_width": 1080, "output_height": 1920}},
                        {"type": "pad_border", "params": {"size": 10, "color": "#000000"}},
                        {"type": "auto_zoom", "params": {"interval_seconds": 5}},
                    ],
                },
            },
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=480,
        )
    )
    workflows.append(
        build_simple_poll_workflow(
            "WF-03 — Split Screen HStack 1280x720",
            video_api_url,
            video_api_key,
            {
                "pipeline_type": "low_level",
                "input_path": "test.mp4",
                "payload": {
                    "output_name": "n8n-wf03-hstack",
                    "operations": [
                        {
                            "type": "hstack",
                            "params": {
                                "second_video": "test_input.mp4",
                                "layout": "horizontal",
                                "output_width": 1280,
                                "output_height": 720,
                            },
                        }
                    ],
                },
            },
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=360,
        )
    )
    workflows.append(
        build_simple_poll_workflow(
            "WF-04 — TikTok Split Screen",
            video_api_url,
            video_api_key,
            {
                "pipeline_type": "low_level",
                "input_path": "test.mp4",
                "payload": {
                    "output_name": "n8n-wf04-tiktok",
                    "operations": [
                        {
                            "type": "split_screen",
                            "params": {
                                "b_roll_video": "test_input.mp4",
                                "split_ratio": 0.5,
                                "audio_source": "mix",
                            },
                        }
                    ],
                },
            },
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=360,
        )
    )
    workflows.append(
        build_simple_poll_workflow(
            "WF-05 — Audio Operations",
            video_api_url,
            video_api_key,
            {
                "pipeline_type": "low_level",
                "input_path": "test_input.mp4",
                "payload": {
                    "output_name": "n8n-wf05-audio",
                    "operations": [
                        {"type": "audio_pitch", "params": {"semitones": 2, "preserve_tempo": True}},
                        {"type": "audio_normalize", "params": {}},
                        {"type": "audio_fade", "params": {"type": "in", "duration": 0.5}},
                    ],
                },
            },
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=240,
        )
    )
    workflows.append(
        build_simple_poll_workflow(
            "WF-06 — Dubbing EN→VI",
            video_api_url,
            video_api_key,
            {
                "pipeline_type": "dubbing",
                "input_path": "test_input.mp4",
                "payload": {
                    "source_language": "en",
                    "target_language": "vi",
                    "translator_service": "google",
                    "tts_voice": "vi-VN-HoaiMyNeural",
                    "tts_rate": "-5%",
                },
            },
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=900,
            poll_seconds=5,
        )
    )
    workflows.append(
        build_simple_poll_workflow(
            "WF-07 — Subtitle Generation",
            video_api_url,
            video_api_key,
            {
                "pipeline_type": "subtitle",
                "input_path": "test_input.mp4",
                "payload": {
                    "language": "auto",
                    "burn_subtitle": True,
                    "font_size": 28,
                },
            },
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=600,
            poll_seconds=5,
        )
    )
    workflows.append(
        build_simple_poll_workflow(
            "WF-08 — Silence Cut",
            video_api_url,
            video_api_key,
            {
                "pipeline_type": "silence_cut",
                "input_path": "test_input.mp4",
                "payload": {
                    "min_silence_duration": 0.3,
                    "silence_threshold_db": -35,
                },
            },
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=360,
        )
    )
    workflows.append(
        build_simple_poll_workflow(
            "WF-09 — Audio Extract",
            video_api_url,
            video_api_key,
            {
                "pipeline_type": "audio-extract",
                "input_path": "test_input.mp4",
                "payload": {"format": "wav"},
            },
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=180,
        )
    )
    workflows.append(
        build_simple_poll_workflow(
            "WF-10 — Ad Video TTS",
            video_api_url,
            video_api_key,
            {
                "pipeline_type": "ad_video",
                "input_path": "test.mp4",
                "payload": {
                    "ad_text": "Sản phẩm chất lượng cao, đặt hàng ngay hôm nay!",
                    "tts_voice": "vi-VN-HoaiMyNeural",
                    "tts_engine": "edge-tts",
                    "burn_subtitle": True,
                },
            },
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=900,
            poll_seconds=5,
        )
    )
    workflows.append(
        build_simple_poll_workflow(
            "WF-11 — Auto B-Roll",
            video_api_url,
            video_api_key,
            {
                "pipeline_type": "auto_broll",
                "input_path": "test.mp4",
                "payload": {"broll_source": "test_input.mp4"},
            },
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=600,
            poll_seconds=5,
        )
    )
    workflows.append(
        build_simple_poll_workflow(
            "WF-12 — Face Track Portrait",
            video_api_url,
            video_api_key,
            {
                "pipeline_type": "face_track_portrait",
                "input_path": "test_input.mp4",
                "payload": {
                    "output_width": 1080,
                    "output_height": 1920,
                },
            },
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=600,
            poll_seconds=5,
        )
    )
    workflows.append(
        build_simple_poll_workflow(
            "WF-13 — Semantic Edit Silence Cut",
            video_api_url,
            video_api_key,
            {
                "pipeline_type": "semantic_edit",
                "input_path": "test_input.mp4",
                "payload": {
                    "command": "silence_cut",
                    "min_silence_duration": 0.3,
                    "silence_threshold_db": -35,
                },
            },
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=600,
            poll_seconds=5,
        )
    )
    workflows.append(
        build_simple_poll_workflow(
            "WF-14 — Split Video Chunks",
            video_api_url,
            video_api_key,
            {
                "pipeline_type": "split_video",
                "input_path": "test.mp4",
                "payload": {"segment_duration": 30},
            },
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=480,
            poll_seconds=5,
        )
    )
    workflows.append(
        build_simple_poll_workflow(
            "WF-15 — Extract Frames",
            video_api_url,
            video_api_key,
            {
                "pipeline_type": "extract_frames",
                "input_path": "test_input.mp4",
                "payload": {
                    "fps": 1,
                    "format": "jpg",
                    "max_frames": 10,
                },
            },
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=240,
        )
    )
    workflows.append(
        build_simple_poll_workflow(
            "WF-16 — Workflow DAG Multi-step",
            video_api_url,
            video_api_key,
            {
                "pipeline_type": "workflow",
                "input_path": "test_input.mp4",
                "payload": {
                    "workflow": {
                        "nodes": {
                            "cut": {"type": "video.cut", "params": {"start": 0, "end": 15}},
                            "scale": {
                                "type": "video.scale",
                                "params": {"width": 1080, "height": 1920},
                                "depends_on": ["cut"],
                            },
                            "border": {
                                "type": "video.pad_border",
                                "params": {"size": 10, "color": "white"},
                                "depends_on": ["scale"],
                            },
                            "export": {"type": "media.finalize", "depends_on": ["border"]},
                        }
                    }
                },
            },
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
            timeout_seconds=600,
            poll_seconds=5,
        )
    )
    workflows.append(
        build_batch_workflow(
            video_api_url,
            video_api_key,
            trigger_mode=trigger_mode,
            webhook_prefix=webhook_prefix,
        )
    )
    return workflows


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an n8n workflow test suite for AI Video Engine.")
    parser.add_argument("--n8n-url", default="http://localhost:5678")
    parser.add_argument("--n8n-api-key", required=True, help="n8n API key (Settings → API)")
    parser.add_argument("--video-api-url", default="http://localhost:6666")
    parser.add_argument("--video-api-key", default="", help="Video Engine API key")
    parser.add_argument("--mode", choices=("http-request", "custom-node"), default="http-request")
    parser.add_argument("--credential-id", default="", help="n8n credential ID for AI Video Engine API")
    parser.add_argument("--credential-name", default="AI Video Engine API")
    parser.add_argument("--input-uri", default="", help="HTTP URL of the source media for custom-node workflows")
    parser.add_argument("--source-key", default="", help="Artifact source_key for custom-node workflows")
    parser.add_argument("--trigger-mode", choices=("manual", "webhook"), default="manual")
    parser.add_argument("--webhook-prefix", default="video-suite")
    parser.add_argument("--dry-run", action="store_true", help="Print JSON, do not upload")
    args = parser.parse_args()

    if args.mode == "custom-node":
        if not args.credential_id:
            raise SystemExit("--credential-id is required for --mode custom-node")
        source_mode = "sourceKey" if args.source_key else "inputUri"
        source_value = args.source_key or args.input_uri
        if not source_value:
            raise SystemExit("--input-uri or --source-key is required for --mode custom-node")
        workflows = all_custom_node_workflows(
            source_value,
            args.credential_id,
            source_mode=source_mode,
            credential_name=args.credential_name,
            trigger_mode=args.trigger_mode,
            webhook_prefix=args.webhook_prefix,
        )
    else:
        workflows = all_workflows(
            args.video_api_url,
            args.video_api_key,
            trigger_mode=args.trigger_mode,
            webhook_prefix=args.webhook_prefix,
        )

    if args.dry_run:
        print(json.dumps(workflows, ensure_ascii=False, indent=2))
        return 0

    print(f"Creating {len(workflows)} workflows on {args.n8n_url} ...")
    created: list[str] = []
    errors: list[str] = []
    for workflow in workflows:
        try:
            workflow_id = create_workflow(args.n8n_url, args.n8n_api_key, workflow)
            trigger_path = workflow_webhook_path(workflow)
            suffix = f" webhook=/{trigger_path}" if trigger_path else ""
            print(f"  [OK] [{workflow_id}] {workflow['name']}{suffix}")
            created.append(workflow_id)
        except RuntimeError as exc:
            print(f"  [FAIL] {workflow['name']}: {exc}", file=sys.stderr)
            errors.append(str(exc))

    print(f"\nDone: {len(created)} created, {len(errors)} errors.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
