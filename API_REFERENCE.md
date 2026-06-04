# AI Video Engine API Reference

> Base URL local: `http://localhost:6666`  
> Phiên bản tài liệu: v2.0  
> Backend dev mặc định: `JOB_BACKEND=memory`  
> Backend production đề xuất: `JOB_BACKEND=supabase`

## 1. Tổng Quan Và Kiến Trúc

AI Video Engine cung cấp FastAPI server để n8n, dashboard, script hoặc ứng dụng nội bộ tạo job xử lý video. API tạo job, upload file, theo dõi tiến độ, hủy job, xem admin, nhận webhook khi job kết thúc và xuất Prometheus metrics.

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
   +-- Embedded worker hoặc worker riêng
   |
   +-- Artifact store local/Supabase
   |
   +-- Webhook callback tới n8n khi job done/failed/cancelled
```

Luồng cơ bản:

1. Client gọi `POST /jobs` hoặc `POST /jobs/upload`.
2. API chuẩn hóa payload, che khóa bí mật và lưu job.
3. Worker claim job, chạy pipeline và cập nhật progress.
4. Client poll `GET /jobs/{id}` hoặc nghe SSE `GET /jobs/{id}/stream`.
5. Khi job kết thúc, API gửi webhook nếu job có `webhook_url`.

## 2. Quick Start - 5 Bước

1. Tạo `.env` từ `.env.example` và đặt port:

```env
API_PORT=6666
API_SECRET_KEY=your-secret-key
API_AUTH_ENABLED=true
JOB_BACKEND=memory
ARTIFACT_STORE_BACKEND=local
```

2. Chạy API:

```bash
python main.py api
```

3. Kiểm tra health:

```bash
curl http://localhost:6666/health
```

4. Tạo job low-level:

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

5. Theo dõi job:

```bash
curl http://localhost:6666/jobs/JOB_ID \
  -H "X-API-Key: your-secret-key"
```

## 3. Xác Thực

Nếu `API_AUTH_ENABLED=true`, mọi endpoint trừ `/health` và `/metrics` cần một trong hai header:

```http
X-API-Key: your-secret-key
```

hoặc:

```http
Authorization: Bearer your-secret-key
```

Nếu sai hoặc thiếu key, API trả:

```json
{"detail": "unauthorized"}
```

Rate limit dùng `API_RATE_LIMIT_PER_MINUTE`. Đặt `0` để tắt giới hạn.

## 4. Bảng Endpoints Tổng Hợp

| Method | Path | Mục đích | Auth |
|---|---|---|---|
| GET | `/health` | Health check | Không |
| GET | `/metrics` | Prometheus metrics | Không |
| POST | `/jobs` | Tạo job từ JSON payload | Có |
| POST | `/jobs/upload` | Upload file và tạo job | Có |
| GET | `/jobs` | Liệt kê job | Có |
| GET | `/jobs/{job_id}` | Xem chi tiết job | Có |
| GET | `/jobs/{job_id}/stream` | Stream progress qua SSE | Có |
| POST | `/jobs/{job_id}/cancel` | Yêu cầu hủy job | Có |
| GET | `/admin` | Dashboard HTML | Có |
| GET | `/admin/jobs` | Danh sách job cho admin | Có |
| GET | `/admin/jobs/{job_id}/assets` | Asset graph của job | Có |
| GET | `/admin/events` | Event log gần đây | Có |
| DELETE | `/admin/jobs/{job_id}/cleanup` | Xóa thư mục temp/output của job | Có |

## 5. POST /jobs

Tạo job bằng JSON. Endpoint này phù hợp cho n8n HTTP Request node, backend app, cron job hoặc script.

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

Input source có thể là:

| Field | Khi dùng |
|---|---|
| `input_uri` | URL `http` hoặc `https` tới video nguồn |
| `source_key` | File đã nằm trong artifact store |
| `input_path` | Chỉ khi `API_ALLOW_INPUT_PATH=true` |
| `source_sha256` | Chỉ khi `API_ALLOW_CLIENT_SOURCE_SHA256=true` |

Response là `JobResponse`.

## 6. POST /jobs/upload

Upload file multipart và tạo job ngay sau khi upload. API tính SHA-256, lưu file vào artifact store với key `uploads/{sha256}/{filename}`, rồi thêm `source_key` vào payload job.

Form fields:

| Field | Type | Mặc định | Ghi chú |
|---|---|---|---|
| `file` | file | Bắt buộc | File video/audio/image tùy pipeline |
| `pipeline_type` | string | `dubbing` | Ví dụ `low_level`, `dubbing` |
| `payload_json` | string JSON | `{}` | Phải là JSON object |
| `metadata_json` | string JSON | `{}` | Phải là JSON object |

Ví dụ:

```bash
curl -X POST http://localhost:6666/jobs/upload \
  -H "X-API-Key: your-secret-key" \
  -F "file=@clip.mp4;type=video/mp4" \
  -F "pipeline_type=low_level" \
  -F 'payload_json={"operations":[{"type":"cut","params":{"duration":3}}]}'
```

Lỗi thường gặp:

| HTTP | Lý do |
|---|---|
| 400 | File rỗng hoặc JSON form không hợp lệ |
| 413 | File lớn hơn `API_UPLOAD_MAX_BYTES` |

## 7. GET /jobs

Liệt kê job mới nhất.

Query:

| Query | Type | Mặc định |
|---|---|---|
| `status` | `pending`, `running`, `done`, `failed`, `cancelled` | Không lọc |
| `limit` | integer 1-200 | 50 |

Ví dụ:

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

## 8. GET /jobs/{id} Và JobResponse Schema

Trả chi tiết một job.

```bash
curl http://localhost:6666/jobs/JOB_ID \
  -H "X-API-Key: your-secret-key"
```

`JobResponse`:

| Field | Type | Ghi chú |
|---|---|---|
| `id` | string | UUID job |
| `status` | string | `pending`, `running`, `done`, `failed`, `cancelled` |
| `pipeline_type` | string | Tên pipeline |
| `priority` | integer | 0-10 |
| `payload` | object | Payload đã chuẩn hóa và đã redact secret |
| `input_path` | string/null | Đường dẫn local nếu được bật |
| `input_uri` | string/null | URL nguồn |
| `output_path` | string/null | Output chính nếu có |
| `source_sha256` | string | Hash nguồn hoặc hash dẫn xuất từ URI |
| `pid` | integer/null | PID tiến trình con nếu có |
| `worker_id` | string/null | Worker đang giữ lease |
| `lease_expires_at` | datetime/null | Hạn lease |
| `cancel_requested` | boolean | Đã yêu cầu hủy |
| `attempt_count` | integer | Số lần worker claim |
| `progress` | integer | 0-100 |
| `step_index` | integer | Bước hiện tại |
| `total_steps` | integer | Tổng số bước |
| `current_step` | string/null | Tên bước hiện tại |
| `log` | string/null | Log tóm tắt nếu pipeline ghi |
| `error` | string/null | Lỗi ngắn |
| `error_detail` | object/null | Lỗi có cấu trúc |
| `metadata` | object | Metadata job, thường có `result_items` |
| `created_at` | datetime | Lúc tạo |
| `started_at` | datetime/null | Lúc worker bắt đầu |
| `finished_at` | datetime/null | Lúc kết thúc |
| `updated_at` | datetime | Lúc cập nhật cuối |

`error_detail`:

```json
{
  "code": "FFMPEG_FAILED",
  "message": "ffmpeg exited with code 1",
  "step": "render",
  "retriable": false
}
```

`metadata.result_items` dùng để client/n8n tìm output:

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

SSE endpoint để nhận progress realtime.

```bash
curl -N http://localhost:6666/jobs/JOB_ID/stream \
  -H "X-API-Key: your-secret-key"
```

Mỗi event trả JSON:

```text
data: {"id":"job-id","progress":50,"step_index":2,"total_steps":4,"current_step":"render","status":"running","error":null,"error_detail":null}
```

Stream tự kết thúc khi job ở trạng thái `done`, `failed` hoặc `cancelled`.

## 10. POST /jobs/{id}/cancel

Yêu cầu hủy job. Nếu job còn `pending`, job chuyển ngay sang `cancelled`. Nếu job đang `running`, API đặt `cancel_requested=true`; worker sẽ dừng an toàn khi kiểm tra cancellation.

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

Dashboard HTML nhẹ để xem job, lọc status và cancel job.

### GET /admin/jobs

Giống `GET /jobs` nhưng mặc định `limit=100`, tối đa 500.

```bash
curl "http://localhost:6666/admin/jobs?status=done&limit=100" \
  -H "X-API-Key: your-secret-key"
```

### GET /admin/jobs/{job_id}/assets

Trả asset graph của job:

```json
{"items": []}
```

Khi asset graph có dữ liệu, mỗi item có `asset_id`, `job_id`, `node_id`, `uri`, `kind`, `parents`, `metadata`.

### GET /admin/events

Trả event log gần đây.

Query:

| Query | Type | Mặc định |
|---|---|---|
| `event_type` | string/null | Không lọc |
| `limit` | integer 1-500 | 100 |

### DELETE /admin/jobs/{job_id}/cleanup

Xóa `TEMP_DIR/{job_id}` và thư mục output theo `job.payload.output_name` nếu có, nếu không dùng `{job_id}`.

Response:

```json
{
  "job_id": "JOB_ID",
  "status": "success",
  "deleted_temp": true,
  "deleted_output": true
}
```

## 12. GET /health Và GET /metrics

`GET /health` không cần auth:

```json
{"status": "ok"}
```

`GET /metrics` trả Prometheus text format nếu `METRICS_ENABLED=true` và dependency metrics được cài.

```bash
curl http://localhost:6666/metrics
```

## 13. Webhook System

Webhook chạy khi job vào terminal state. URL lấy theo thứ tự:

1. `job.metadata.webhook_url`
2. `job.payload.webhook_url`

`JobManager` bật webhook theo mặc định khi khởi tạo trực tiếp. Khi chạy qua service runtime, biến `WEBHOOKS_ENABLED` trong cấu hình sẽ gán lại `JobManager.webhooks_enabled`; vì vậy production nên đặt `WEBHOOKS_ENABLED=true` nếu muốn gửi callback. Dispatch chạy trong background thread và dùng timeout `WEBHOOK_TIMEOUT_SECONDS`.

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

Nên cấu hình n8n Webhook Trigger node để nhận `POST`, sau đó dùng IF node kiểm tra:

```text
{{$json.status}} == "done"
{{$json.status}} == "failed"
```

## 14. n8n Integration Guide

### HTTP Request Node - tạo job

Config:

| Setting | Value |
|---|---|
| Method | `POST` |
| URL | `http://localhost:6666/jobs` |
| Authentication | None hoặc Header Auth |
| Header | `X-API-Key: your-secret-key` |
| Body Content Type | JSON |

Body mẫu:

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

API sẽ lưu secret vào secret store và trả payload đã redact:

```json
{"api_key": "***1234", "api_key_source": "request", "api_key_hint": "***1234"}
```

### Webhook Trigger Node - nhận callback

Config:

| Setting | Value |
|---|---|
| HTTP Method | `POST` |
| Path | `video-done` |
| Response Mode | `On Received` |

### Error Handling

Dùng IF/Switch node:

| Điều kiện | Hành động |
|---|---|
| `status == "done"` | Lấy `metadata.result_items` |
| `status == "failed"` | Gửi alert kèm `error_detail` |
| `status == "cancelled"` | Ghi log hoặc kết thúc workflow |

## 15. Payload Reference

### Payload chung

| Field | Type | Ghi chú |
|---|---|---|
| `request` | string | Mô tả tự nhiên từ UI/n8n |
| `time_range` | object | `start`, `end`, `duration`; cascade xuống operation |
| `operations` | array | Danh sách bước low-level |
| `providers` | object | Cấu hình AI providers, secret được redact |
| `webhook_url` | string | Callback URL |
| `target_language` | string | Dubbing/subtitle |
| `target_languages` | array | Multilang dubbing |
| `tts_voice` | string | Voice TTS |
| `source_language` | string | Ngôn ngữ nguồn |

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

Parser chuẩn hóa thành:

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

Operations phổ biến:

| Type | Params chính |
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

## 16. Mã Lỗi HTTP

| HTTP | Ý nghĩa | Ví dụ |
|---|---|---|
| 200 | Thành công | Job created/listed |
| 400 | Request không hợp lệ | Pipeline không hỗ trợ, JSON sai, input scheme bị chặn |
| 401 | Unauthorized | Thiếu hoặc sai API key |
| 404 | Không tìm thấy | Job ID không tồn tại |
| 413 | Payload quá lớn | Upload vượt `API_UPLOAD_MAX_BYTES` |
| 429 | Rate limited | Vượt `API_RATE_LIMIT_PER_MINUTE` |
| 500 | Lỗi server | Lỗi không mong đợi |

Job-level error nằm trong `JobResponse.error` và `JobResponse.error_detail`, không nhất thiết là HTTP error.

## 17. Environment Variables Reference

| Biến | Mặc định | Ghi chú |
|---|---|---|
| `APP_NAME` | `ai-video-engine` | Tên app |
| `LOG_LEVEL` | `INFO` | Mức log |
| `JOB_BACKEND` | `memory` | `memory` hoặc `supabase` |
| `ARTIFACT_STORE_BACKEND` | `local` | `local` hoặc `supabase` |
| `SUPABASE_URL` | rỗng | URL Supabase |
| `SUPABASE_KEY` | rỗng | Service role key |
| `SUPABASE_JOBS_TABLE` | `jobs` | Bảng job |
| `SUPABASE_STORAGE_BUCKET` | `artifacts` | Bucket artifact |
| `SECRET_STORE_BACKEND` | `memory` | `memory` hoặc `supabase`; cần `supabase` khi worker tách process và job có per-job provider key |
| `OUTPUT_DIR` | `output` | Thư mục output |
| `TEMP_DIR` | `temp` | Thư mục tạm |
| `CACHE_DIR` | `cache` | Thư mục cache |
| `MAX_WORKERS` | `2` | Số worker song song |
| `API_HOST` | `0.0.0.0` | Host bind |
| `API_PORT` | `6666` | Port API |
| `API_SECRET_KEY` | `change-me-in-production` | API key |
| `API_AUTH_ENABLED` | `true` | Bật auth |
| `API_EMBEDDED_WORKER` | `true` | API tự chạy worker nền |
| `API_ALLOW_INPUT_PATH` | `false` | Cho phép local path |
| `API_ALLOW_CLIENT_SOURCE_SHA256` | `false` | Cho phép client gửi SHA trực tiếp |
| `API_ALLOWED_INPUT_URI_SCHEMES` | `http,https` | Scheme input URI |
| `API_ALLOW_PRIVATE_NETWORK_URLS` | `false` | Cho phép `input_uri`/`webhook_url` trỏ localhost/private network cho local dev |
| `API_UPLOAD_MAX_BYTES` | `536870912` | Giới hạn upload |
| `API_RATE_LIMIT_PER_MINUTE` | `60` | Rate limit mỗi API key |
| `WEBHOOKS_ENABLED` | `false` | Bật webhook |
| `WEBHOOK_TIMEOUT_SECONDS` | `10` | Timeout gửi webhook |
| `METRICS_ENABLED` | `true` | Bật `/metrics` |
| `TRACING_ENABLED` | `false` | Bật tracing |

Scripts kiểm thử live:

```bash
python scripts/test_api_live.py --base-url http://localhost:6666 --api-key your-secret-key
python scripts/test_webhook_live.py --base-url http://localhost:6666 --api-key your-secret-key --webhook-port 9999
```
