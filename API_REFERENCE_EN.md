# AI Video Engine API Reference

> Local base URL: `http://localhost:6666`  
> Documentation version: v2.0  
> Default dev backend: `JOB_BACKEND=memory`  
> Recommended production backend: `JOB_BACKEND=supabase`

## 1. Overview And Architecture

AI Video Engine exposes a FastAPI server for n8n, dashboards, scripts, or internal apps. The API can create jobs, upload files, stream progress, cancel jobs, serve admin views, send terminal webhooks, and expose Prometheus metrics.

```text
n8n / client
   |
   | HTTP + X-API-Key
   v
FastAPI :6666
   |
   +-- JobManager
   |     +-- memory repository (dev)
   |     +-- Supabase repository (prod)
   |
   +-- Embedded worker or standalone worker
   |
   +-- Local/Supabase artifact store
   |
   +-- Webhook callback to n8n when a job is done/failed/cancelled
```

Basic flow:

1. A client calls `POST /jobs` or `POST /jobs/upload`.
2. The API normalizes payloads, redacts secrets, and stores the job.
3. A worker claims the job, runs the pipeline, and updates progress.
4. The client polls `GET /jobs/{id}` or subscribes to `GET /jobs/{id}/stream`.
5. When the job reaches a terminal state, the API sends a webhook if `webhook_url` is present.

## 2. Quick Start - 5 Steps

1. Create `.env` from `.env.example`:

```env
API_PORT=6666
API_SECRET_KEY=your-secret-key
API_AUTH_ENABLED=true
JOB_BACKEND=memory
ARTIFACT_STORE_BACKEND=local
```

2. Start the API:

```bash
python main.py api
```

3. Check health:

```bash
curl http://localhost:6666/health
```

4. Create a low-level job:

```bash
curl -X POST http://localhost:6666/jobs \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-key" \
  -d '{
    "pipeline_type": "low_level",
    "input_uri": "https://example.com/video.mp4",
    "payload": {
      "operations": [
        {"type": "cut", "params": {"start": 0, "duration": 3}}
      ]
    }
  }'
```

5. Inspect the job:

```bash
curl http://localhost:6666/jobs/JOB_ID \
  -H "X-API-Key: your-secret-key"
```

## 3. Authentication

When `API_AUTH_ENABLED=true`, every endpoint except `/health` and `/metrics` requires one of these headers:

```http
X-API-Key: your-secret-key
```

or:

```http
Authorization: Bearer your-secret-key
```

Unauthorized requests return:

```json
{"detail": "unauthorized"}
```

Rate limiting is controlled by `API_RATE_LIMIT_PER_MINUTE`. Set it to `0` to disable rate limiting.

## 4. Endpoint Summary

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/health` | Health check | No |
| GET | `/metrics` | Prometheus metrics | No |
| POST | `/jobs` | Create a job from JSON | Yes |
| POST | `/jobs/upload` | Upload a file and create a job | Yes |
| GET | `/jobs` | List jobs | Yes |
| GET | `/jobs/{job_id}` | Get job details | Yes |
| GET | `/jobs/{job_id}/stream` | Stream progress via SSE | Yes |
| POST | `/jobs/{job_id}/cancel` | Request cancellation | Yes |
| GET | `/admin` | HTML admin dashboard | Yes |
| GET | `/admin/jobs` | Admin job list | Yes |
| GET | `/admin/jobs/{job_id}/assets` | Job asset graph | Yes |
| GET | `/admin/events` | Recent events | Yes |
| DELETE | `/admin/jobs/{job_id}/cleanup` | Delete temp/output folders | Yes |

## 5. POST /jobs

Creates a job from a JSON payload. This is the main endpoint for n8n HTTP Request nodes, backend apps, cron jobs, and scripts.

Request:

```json
{
  "pipeline_type": "low_level",
  "input_uri": "https://example.com/video.mp4",
  "source_key": null,
  "source_sha256": null,
  "payload": {
    "time_range": {"start": 0, "duration": 3},
    "operations": [
      {"id": "cut-main", "type": "cut", "params": {"start": 0, "duration": 3}}
    ],
    "webhook_url": "http://localhost:9999/webhook"
  },
  "metadata": {
    "request_id": "n8n-001"
  },
  "priority": 5
}
```

Supported source fields:

| Field | Usage |
|---|---|
| `input_uri` | Source video URL using `http` or `https` |
| `source_key` | Object already stored in the artifact store |
| `input_path` | Local path, only when `API_ALLOW_INPUT_PATH=true` |
| `source_sha256` | Direct SHA-256, only when `API_ALLOW_CLIENT_SOURCE_SHA256=true` |

The response is a `JobResponse`.

## 6. POST /jobs/upload

Uploads a multipart file and creates a job. The API computes SHA-256, stores the file as `uploads/{sha256}/{filename}`, and injects `source_key` into the job payload.

Form fields:

| Field | Type | Default | Notes |
|---|---|---|---|
| `file` | file | Required | Media file |
| `pipeline_type` | string | `dubbing` | Example: `low_level` |
| `payload_json` | JSON string | `{}` | Must be a JSON object |
| `metadata_json` | JSON string | `{}` | Must be a JSON object |

Example:

```bash
curl -X POST http://localhost:6666/jobs/upload \
  -H "X-API-Key: your-secret-key" \
  -F "file=@clip.mp4;type=video/mp4" \
  -F "pipeline_type=low_level" \
  -F 'payload_json={"operations":[{"type":"cut","params":{"duration":3}}]}'
```

Common failures:

| HTTP | Reason |
|---|---|
| 400 | Empty file or invalid JSON form field |
| 413 | File exceeds `API_UPLOAD_MAX_BYTES` |

## 7. GET /jobs

Lists recent jobs.

Query parameters:

| Query | Type | Default |
|---|---|---|
| `status` | `pending`, `running`, `done`, `failed`, `cancelled` | No filter |
| `limit` | integer 1-200 | 50 |

Example:

```bash
curl "http://localhost:6666/jobs?status=running&limit=20" \
  -H "X-API-Key: your-secret-key"
```

Response:

```json
{
  "items": [
    {
      "id": "job-id",
      "status": "running",
      "pipeline_type": "low_level",
      "priority": 0,
      "payload": {},
      "source_sha256": "sha256-or-derived-hash",
      "cancel_requested": false,
      "attempt_count": 1,
      "progress": 35,
      "step_index": 1,
      "total_steps": 3,
      "metadata": {},
      "created_at": "2026-05-09T12:00:00+00:00",
      "updated_at": "2026-05-09T12:01:00+00:00"
    }
  ]
}
```

## 8. GET /jobs/{id} And JobResponse Schema

Returns one job.

```bash
curl http://localhost:6666/jobs/JOB_ID \
  -H "X-API-Key: your-secret-key"
```

`JobResponse`:

| Field | Type | Notes |
|---|---|---|
| `id` | string | Job UUID |
| `status` | string | `pending`, `running`, `done`, `failed`, `cancelled` |
| `pipeline_type` | string | Pipeline name |
| `priority` | integer | 0-10 |
| `payload` | object | Normalized payload with secrets redacted |
| `input_path` | string/null | Local path if enabled |
| `input_uri` | string/null | Source URL |
| `output_path` | string/null | Main output path |
| `source_sha256` | string | Source hash or URI-derived hash |
| `pid` | integer/null | Child process PID if present |
| `worker_id` | string/null | Worker currently holding the lease |
| `lease_expires_at` | datetime/null | Lease expiration |
| `cancel_requested` | boolean | Cancellation requested |
| `attempt_count` | integer | Number of claims |
| `progress` | integer | 0-100 |
| `step_index` | integer | Current step index |
| `total_steps` | integer | Total steps |
| `current_step` | string/null | Current step name |
| `log` | string/null | Optional pipeline log summary |
| `error` | string/null | Short error |
| `error_detail` | object/null | Structured error |
| `metadata` | object | Job metadata, often including `result_items` |
| `created_at` | datetime | Creation time |
| `started_at` | datetime/null | Worker start time |
| `finished_at` | datetime/null | Terminal time |
| `updated_at` | datetime | Last update time |

`error_detail`:

```json
{
  "code": "FFMPEG_FAILED",
  "message": "ffmpeg exited with code 1",
  "step": "render",
  "retriable": false
}
```

`metadata.result_items` helps clients and n8n find outputs:

```json
{
  "result_items": [
    {
      "id": "job:node:video:1",
      "operation_id": "cut-main",
      "kind": "video",
      "label": "Video",
      "path": "output/job-id/final.mp4",
      "media_type": "video",
      "artifact_scope": "output",
      "relative_path": "job-id/final.mp4"
    }
  ]
}
```

## 9. GET /jobs/{id}/stream

Server-Sent Events endpoint for realtime progress.

```bash
curl -N http://localhost:6666/jobs/JOB_ID/stream \
  -H "X-API-Key: your-secret-key"
```

Each event contains JSON:

```text
data: {"id":"job-id","progress":50,"step_index":2,"total_steps":4,"current_step":"render","status":"running","error":null,"error_detail":null}
```

The stream ends when the job status is `done`, `failed`, or `cancelled`.

## 10. POST /jobs/{id}/cancel

Requests cancellation. A `pending` job becomes `cancelled` immediately. A `running` job gets `cancel_requested=true`; the worker stops safely when it checks cancellation.

```bash
curl -X POST http://localhost:6666/jobs/JOB_ID/cancel \
  -H "X-API-Key: your-secret-key"
```

Response:

```json
{
  "id": "JOB_ID",
  "cancel_requested": true,
  "status": "cancelled"
}
```

## 11. Admin Endpoints

### GET /admin

Small HTML dashboard for viewing jobs, filtering by status, and cancelling jobs.

### GET /admin/jobs

Same shape as `GET /jobs`, but defaults to `limit=100` and allows up to 500.

```bash
curl "http://localhost:6666/admin/jobs?status=done&limit=100" \
  -H "X-API-Key: your-secret-key"
```

### GET /admin/jobs/{job_id}/assets

Returns the job asset graph:

```json
{"items": []}
```

When available, each item includes `asset_id`, `job_id`, `node_id`, `uri`, `kind`, `parents`, and `metadata`.

### GET /admin/events

Returns recent event log items.

Query:

| Query | Type | Default |
|---|---|---|
| `event_type` | string/null | No filter |
| `limit` | integer 1-500 | 100 |

### DELETE /admin/jobs/{job_id}/cleanup

Deletes `TEMP_DIR/{job_id}` and the output folder named by `job.payload.output_name`, or `{job_id}` when no output name is present.

Response:

```json
{
  "job_id": "JOB_ID",
  "status": "success",
  "deleted_temp": true,
  "deleted_output": true
}
```

## 12. GET /health And GET /metrics

`GET /health` is public:

```json
{"status": "ok"}
```

`GET /metrics` returns Prometheus text format when `METRICS_ENABLED=true` and the metrics dependency is installed.

```bash
curl http://localhost:6666/metrics
```

## 13. Webhook System

Webhooks are sent when a job reaches a terminal state. The URL is resolved in this order:

1. `job.metadata.webhook_url`
2. `job.payload.webhook_url`

`JobManager` enables webhooks by default when instantiated directly. When services are built from runtime settings, `WEBHOOKS_ENABLED` is applied to `JobManager.webhooks_enabled`; production deployments should set `WEBHOOKS_ENABLED=true` when callbacks are expected. Dispatch happens in a background thread and uses `WEBHOOK_TIMEOUT_SECONDS`.

Event mapping:

| Job status | Event |
|---|---|
| `done` | `job.completed` |
| `failed` | `job.failed` |
| `cancelled` | `job.cancelled` |

Webhook payload:

```json
{
  "event": "job.completed",
  "job_id": "JOB_ID",
  "status": "done",
  "output_path": "output/job/final.mp4",
  "metadata": {
    "result_items": []
  },
  "error": null,
  "error_detail": null
}
```

In n8n, use a Webhook Trigger node that accepts `POST`, then an IF node:

```text
{{$json.status}} == "done"
{{$json.status}} == "failed"
```

## 14. n8n Integration Guide

### HTTP Request Node - create job

Config:

| Setting | Value |
|---|---|
| Method | `POST` |
| URL | `http://localhost:6666/jobs` |
| Authentication | None or header auth |
| Header | `X-API-Key: your-secret-key` |
| Body Content Type | JSON |

Body example:

```json
{
  "pipeline_type": "low_level",
  "input_uri": "{{$json.video_url}}",
  "payload": {
    "webhook_url": "http://localhost:5678/webhook/video-done",
    "time_range": {"start": 0, "duration": 10},
    "operations": [
      {"id": "cut-1", "type": "cut", "params": {}},
      {"id": "scale-1", "type": "scale", "params": {"width": 1080, "height": 1920}}
    ],
    "providers": {
      "tts": {
        "provider": "elevenlabs",
        "api_key": "{{$env.ELEVENLABS_API_KEY}}"
      }
    }
  },
  "metadata": {
    "workflow_id": "{{$workflow.id}}",
    "execution_id": "{{$execution.id}}"
  }
}
```

The API stores secrets in the secret store and returns a redacted payload:

```json
{"api_key": "***1234", "api_key_source": "request", "api_key_hint": "***1234"}
```

### Webhook Trigger Node - receive callback

Config:

| Setting | Value |
|---|---|
| HTTP Method | `POST` |
| Path | `video-done` |
| Response Mode | `On Received` |

### Error Handling

Use an IF/Switch node:

| Condition | Action |
|---|---|
| `status == "done"` | Read `metadata.result_items` |
| `status == "failed"` | Alert with `error_detail` |
| `status == "cancelled"` | Log or end the workflow |

## 15. Payload Reference

### Common payload fields

| Field | Type | Notes |
|---|---|---|
| `request` | string | Natural-language request from UI/n8n |
| `time_range` | object | `start`, `end`, `duration`; cascades to operations |
| `operations` | array | Low-level operation list |
| `providers` | object | AI provider config; secrets are redacted |
| `webhook_url` | string | Callback URL |
| `target_language` | string | Dubbing/subtitle target |
| `target_languages` | array | Multilingual dubbing targets |
| `tts_voice` | string | TTS voice |
| `source_language` | string | Source language |

### Operation object

```json
{
  "id": "scale-main",
  "type": "scale",
  "params": {
    "width": 1080,
    "height": 1920
  }
}
```

The parser normalizes it to:

```json
{
  "id": "scale-main",
  "operation_id": "scale-main",
  "type": "scale",
  "name": "scale",
  "width": 1080,
  "height": 1920
}
```

Common operations:

| Type | Main params |
|---|---|
| `cut` | `start`, `end`, `duration` |
| `scale` | `width`, `height`, `force_original_aspect_ratio` |
| `crop` | `x`, `y`, `width`, `height` |
| `concat` | `inputs` |
| `overlay` | `overlay_path`, `x`, `y` |
| `watermark` | `image_path`, `position`, `opacity` |
| `subtitle_burn` | `subtitle_path`, `font_size` |
| `remux_audio` | `audio_path` |
| `speed` | `factor` |
| `rotate` | `angle` |
| `flip` | `mode` |
| `blur_bg_portrait` | `width`, `height` |
| `platform_reframe` | `platform`, `aspect_ratio` |
| `split_video` | `segments` |
| `extract_frames` | `fps`, `timestamps` |
| `convert` | `format`, `codec` |
| `chromakey` | `color`, `similarity`, `blend` |
| `delogo` | `x`, `y`, `width`, `height` |
| `grid` | `rows`, `cols` |
| `hstack` | `inputs` |
| `loop` | `count`, `duration` |

Provider config:

```json
{
  "providers": {
    "translation": {"provider": "deepl", "api_key": "secret"},
    "tts": {"provider": "openai", "api_key": "secret", "model": "gpt-4o-mini-tts"}
  }
}
```

## 16. HTTP Error Codes

| HTTP | Meaning | Example |
|---|---|---|
| 200 | Success | Job created/listed |
| 400 | Invalid request | Unsupported pipeline, invalid JSON, blocked input scheme |
| 401 | Unauthorized | Missing or invalid API key |
| 404 | Not found | Unknown job ID |
| 413 | Payload too large | Upload exceeds `API_UPLOAD_MAX_BYTES` |
| 429 | Rate limited | Exceeds `API_RATE_LIMIT_PER_MINUTE` |
| 500 | Server error | Unexpected failure |

Job-level errors are stored in `JobResponse.error` and `JobResponse.error_detail`; they are not always HTTP errors.

## 17. Environment Variables Reference

| Variable | Default | Notes |
|---|---|---|
| `APP_NAME` | `ai-video-engine` | App name |
| `LOG_LEVEL` | `INFO` | Log level |
| `JOB_BACKEND` | `memory` | `memory` or `supabase` |
| `ARTIFACT_STORE_BACKEND` | `local` | `local` or `supabase` |
| `SECRET_STORE_BACKEND` | `memory` | `memory` or `supabase`; use `supabase` when workers are separate and jobs carry per-job provider keys |
| `SUPABASE_URL` | empty | Supabase URL |
| `SUPABASE_KEY` | empty | Service role key |
| `SUPABASE_JOBS_TABLE` | `jobs` | Jobs table |
| `SUPABASE_STORAGE_BUCKET` | `artifacts` | Artifact bucket |
| `OUTPUT_DIR` | `output` | Output folder |
| `TEMP_DIR` | `temp` | Temporary folder |
| `CACHE_DIR` | `cache` | Cache folder |
| `MAX_WORKERS` | `2` | Parallel workers |
| `API_HOST` | `0.0.0.0` | Bind host |
| `API_PORT` | `6666` | API port |
| `API_SECRET_KEY` | `change-me-in-production` | API key |
| `API_AUTH_ENABLED` | `true` | Enable auth |
| `API_EMBEDDED_WORKER` | `true` | Run a background worker in API process |
| `API_ALLOW_INPUT_PATH` | `false` | Allow local input paths |
| `API_ALLOW_CLIENT_SOURCE_SHA256` | `false` | Allow direct client SHA-256 |
| `API_ALLOWED_INPUT_URI_SCHEMES` | `http,https` | Allowed input URI schemes |
| `API_ALLOW_PRIVATE_NETWORK_URLS` | `false` | Allow `input_uri`/`webhook_url` to target localhost/private networks for local development |
| `API_UPLOAD_MAX_BYTES` | `536870912` | Upload limit |
| `API_RATE_LIMIT_PER_MINUTE` | `60` | Per-key rate limit |
| `WEBHOOKS_ENABLED` | `false` | Enable webhooks |
| `WEBHOOK_TIMEOUT_SECONDS` | `10` | Webhook timeout |
| `METRICS_ENABLED` | `true` | Enable `/metrics` |
| `TRACING_ENABLED` | `false` | Enable tracing |

Live test scripts:

```bash
python scripts/test_api_live.py --base-url http://localhost:6666 --api-key your-secret-key
python scripts/test_webhook_live.py --base-url http://localhost:6666 --api-key your-secret-key --webhook-port 9999
```
