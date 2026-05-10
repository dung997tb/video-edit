# 📋 Kế Hoạch Đầy Đủ — Đánh Giá, Test & API Docs
## AI Video Engine — v2.0 Implementation Plan

> **Trạng thái**: Chờ phê duyệt — Chưa thực thi  
> **Port**: `6666` (thay thế 8000)  
> **Backend**: `memory` (dev) / `supabase` (prod)  
> **n8n**: self-hosted, cùng VPS  

---

## 🗺️ Kiến Trúc Hệ Thống Hiện Tại

```
┌─────────────────────────────────────────────────────────┐
│                      VPS Server                         │
│                                                         │
│  ┌──────────────┐     ┌────────────────────────────┐   │
│  │     n8n      │────▶│   AI Video Engine API      │   │
│  │ (self-hosted)│     │   FastAPI :6666             │   │
│  └──────────────┘     │                            │   │
│         ▲             │  ┌─────────┐ ┌──────────┐  │   │
│         │             │  │  Queue  │ │  Worker  │  │   │
│    webhook POST        │  │(memory/ │ │(embedded)│  │   │
│    on job done         │  │supabase)│ └──────────┘  │   │
│                        │  └─────────┘               │   │
│  ┌──────────────┐     └────────────────────────────┘   │
│  │  Supabase    │◀────── job records (prod mode)        │
│  │  PostgreSQL  │                                       │
│  └──────────────┘                                       │
└─────────────────────────────────────────────────────────┘
         ▲
    internet (optional: domain + nginx)
```

---

## 📊 Đánh Giá Hiện Trạng Chi Tiết

### ✅ Đã Có & Ổn Định
| Component | File | Ghi chú |
|---|---|---|
| Job CRUD API | `api/routes/jobs.py` | POST/GET/LIST/CANCEL |
| Auth middleware | `api/main.py` | X-API-Key + Bearer |
| Rate limiter | `api/middleware/rate_limit.py` | Sliding window 60s |
| Admin dashboard | `api/routes/admin.py` | HTML + 5 JSON endpoints |
| Webhook dispatch | `core/job_manager.py:631` | Async thread, timeout |
| SSE streaming | `api/routes/jobs.py:202` | `text/event-stream` |
| File upload | `api/routes/jobs.py:110` | Chunked, SHA256, 512MB |
| Payload parser | `core/payload_parser.py` | structured → flat |
| Key redaction | `core/key_redactor.py` | providers.*.api_key |
| result_items | `core/result_manifest.py` | ResultItem dataclass |
| Supabase repo | `core/job_manager.py:277` | claim_jobs, RPC |
| Schema SQL | `supabase/schema.sql` | Đầy đủ indexes + RPCs |
| Pipeline runner | `core/pipeline.py` | DAG, heartbeat, cache |
| 36 test files | `tests/` | Unit tests phong phú |

### ⚠️ Khoảng Trống Cần Bổ Sung

| Khoảng trống | Mức độ | Lý do |
|---|---|---|
| Port 8000 vẫn còn trong docs | 🔴 Cao | Cần đổi thành 6666 |
| Test webhook (8 test cases) | 🔴 Cao | Chỉ có code, chưa có test |
| Test admin endpoints (6 cases) | 🔴 Cao | `admin.py` không có test file |
| Test upload flow (6 cases) | 🔴 Cao | `test_api_payload_integration.py` chỉ test JSON jobs |
| Test n8n payload compat (6 cases) | 🔴 Cao | Payload format n8n chưa được verify end-to-end |
| Test Supabase repo (5 cases) | 🟡 Trung | `SupabaseJobRepository` chưa có test |
| Test rate limiter (4 cases) | 🟡 Trung | `InMemoryRateLimiter` chưa có test riêng |
| Live smoke test script | 🟡 Trung | Chỉ có `scripts/smoke_prod.ps1` (PowerShell) |
| Webhook e2e script | 🟡 Trung | Chưa có |
| `openapi.yaml` spec | 🔴 Cao | Chưa có |
| `API_REFERENCE.md` (VI) | 🔴 Cao | Thiếu: Admin endpoints, timestamps, webhook schema |
| `API_REFERENCE_EN.md` | 🔴 Cao | Chưa có |

---

## 📁 Danh Sách Files Cần Tạo/Sửa

### Nhóm A — Test Files (Tạo mới)

#### [NEW] `tests/test_webhook_dispatch.py`
**Mục tiêu**: Kiểm tra toàn bộ cơ chế webhook của `JobManager`  
**Test cases** (8 cases):
```
1. test_webhook_called_on_complete
   └─ complete_job() → kiểm tra HTTP POST đến mock URL với event="job.completed"

2. test_webhook_called_on_fail
   └─ fail_job() → kiểm tra event="job.failed", có error, error_detail

3. test_webhook_called_on_cancel
   └─ fail_job(cancelled=True) → kiểm tra event="job.cancelled"

4. test_webhook_skipped_when_no_url
   └─ metadata/payload không có webhook_url → không gọi HTTP

5. test_webhook_payload_schema
   └─ Verify đủ fields: event, job_id, status, output_path, metadata, error, error_detail

6. test_webhook_url_from_metadata
   └─ webhook_url trong job.metadata

7. test_webhook_url_from_payload
   └─ webhook_url trong job.payload

8. test_webhook_timeout_nonblocking
   └─ Mock server chậm 10s → job manager không bị block
```
**Kỹ thuật**: `http.server.BaseHTTPRequestHandler` + thread mock server, `unittest.mock.patch`

---

#### [NEW] `tests/test_admin_routes.py`
**Mục tiêu**: Kiểm tra tất cả endpoint của `api/routes/admin.py`  
**Test cases** (6 cases):
```
1. test_admin_dashboard_html
   └─ GET /admin → 200, Content-Type: text/html

2. test_admin_jobs_returns_list
   └─ GET /admin/jobs → {"items": [...]}

3. test_admin_jobs_filter_status
   └─ GET /admin/jobs?status=done → chỉ trả jobs done

4. test_admin_job_assets_empty
   └─ GET /admin/jobs/{id}/assets → {"items": []} khi không có graph

5. test_admin_events_empty
   └─ GET /admin/events → {"items": []} khi event bus rỗng

6. test_admin_cleanup_removes_dirs
   └─ DELETE /admin/jobs/{id}/cleanup → deleted_temp/deleted_output=True
```

---

#### [NEW] `tests/test_api_upload.py`
**Mục tiêu**: Kiểm tra `/jobs/upload` multipart endpoint  
**Test cases** (6 cases):
```
1. test_upload_creates_job_successfully
   └─ Upload 1KB fake mp4 → 200, trả job với source_sha256

2. test_upload_exceeds_max_bytes
   └─ Upload > API_UPLOAD_MAX_BYTES → 413

3. test_upload_empty_file
   └─ Upload file 0 bytes → 400

4. test_upload_invalid_payload_json
   └─ payload_json = "not json" → 400

5. test_upload_sha256_matches_content
   └─ Verify source_sha256 trong job = sha256 của file upload

6. test_upload_source_key_stored_in_artifact_store
   └─ Verify artifact_store có key uploads/{sha256}/{filename}
```

---

#### [NEW] `tests/test_n8n_payload_compat.py`
**Mục tiêu**: Verify toàn bộ n8n payload format hoạt động đúng  
**Test cases** (6 cases):
```
1. test_n8n_low_level_full_schema
   └─ payload với request, time_range, operations[{id,type,params}], providers
   └─ Verify: operations normalized, time_range cascade, key redacted

2. test_n8n_dubbing_payload
   └─ pipeline_type=dubbing, payload={target_language, tts_voice, webhook_url}
   └─ Verify job created, webhook_url trong payload

3. test_n8n_multilang_dubbing
   └─ payload={target_languages:["en","ja","ko"]}

4. test_n8n_source_key_flow
   └─ payload có source_key (không có input_uri) → job với source_key trong payload

5. test_n8n_provider_key_multi
   └─ providers với tts + translation đều có api_key
   └─ Verify cả 2 key đều bị redact và lưu vào secret_store

6. test_n8n_webhook_url_triggers_dispatch
   └─ job với webhook_url → complete → verify mock server nhận POST
```

---

#### [NEW] `tests/test_rate_limit.py`
**Mục tiêu**: Kiểm tra `InMemoryRateLimiter`  
**Test cases** (4 cases):
```
1. test_allows_under_limit
   └─ 5 requests với limit=10 → tất cả True

2. test_blocks_over_limit
   └─ 11 requests với limit=10 → request thứ 11 False

3. test_window_resets_after_60s
   └─ Mock time: gửi 10 req → advance 61s → gửi 10 req nữa → tất cả allowed

4. test_zero_limit_disables_rate_limiting
   └─ limit=0 → vô số request → tất cả True
```

---

#### [NEW] `tests/test_supabase_repo.py`
**Mục tiêu**: Kiểm tra `SupabaseJobRepository` với mock Supabase client  
**Test cases** (5 cases):
```
1. test_create_job_calls_insert
   └─ Verify client.table().insert().execute() được gọi

2. test_get_job_returns_none_when_not_found
   └─ Mock response.data = [] → get_job returns None

3. test_claim_jobs_calls_rpc
   └─ Verify client.rpc("claim_jobs", {...}).execute() được gọi

4. test_complete_job_updates_status_done
   └─ Verify update payload có status="done", finished_at, progress=100

5. test_request_cancel_fallback_to_direct_update
   └─ RPC fails → fallback to direct .update()
```

---

### Nhóm B — Integration Scripts (Tạo mới)

#### [NEW] `scripts/test_api_live.py`
**Mục tiêu**: Smoke test với server đang chạy thực  
**Cách dùng**:
```bash
python scripts/test_api_live.py \
  --base-url http://localhost:6666 \
  --api-key your-secret-key \
  [--input-uri https://example.com/video.mp4]
```
**Flow thực hiện**:
```
Step 1: GET /health → assert status="ok"
Step 2: POST /jobs (pipeline_type=low_level, cut 0-3s) → lấy job_id
Step 3: GET /jobs/{id} → assert pending/running/done
Step 4: GET /jobs → assert list có job vừa tạo
Step 5: Tạo job mới → POST /jobs/{id}/cancel → assert cancel_requested=True
Step 6: GET /jobs?status=cancelled → verify job trong list
Step 7: GET /admin/jobs → verify admin API
Step 8: GET /metrics → verify prometheus endpoint
→ Print summary: PASSED/FAILED với thời gian
```

---

#### [NEW] `scripts/test_webhook_live.py`
**Mục tiêu**: Test webhook end-to-end với mock HTTP server  
**Cách dùng**:
```bash
python scripts/test_webhook_live.py \
  --base-url http://localhost:6666 \
  --api-key your-secret-key \
  --webhook-port 9999 \
  [--input-uri https://example.com/short.mp4]
```
**Flow**:
```
Step 1: Khởi động mock HTTP server trên port 9999 (background thread)
Step 2: Tạo job với webhook_url=http://localhost:9999/webhook
Step 3: Poll GET /jobs/{id} mỗi 2s, timeout 120s
Step 4: Khi status=done|failed → verify mock server đã nhận POST
Step 5: In webhook payload nhận được
Step 6: Assert: event đúng, job_id đúng, metadata có result_items
→ PASSED/FAILED + thời gian xử lý
```

---

### Nhóm C — Cấu hình (Sửa đổi)

#### [MODIFY] `.env.example`
- Đổi `API_PORT=8000` → `API_PORT=6666`

#### [MODIFY] `config/settings.py` (hoặc file config tương đương)
- Cập nhật default port từ 8000 → 6666

---

### Nhóm D — Tài liệu (Tạo mới / Viết lại)

#### [OVERWRITE] `API_REFERENCE.md` — Tiếng Việt, đầy đủ
**Cấu trúc mới** (14 sections):
```
1. Tổng quan & Kiến trúc (diagram)
2. Quick Start — 5 bước
3. Xác thực (Authentication)
4. Bảng endpoints tổng hợp (tất cả, kể cả /admin)
5. POST /jobs
6. POST /jobs/upload
7. GET /jobs
8. GET /jobs/{id} + JobResponse schema đầy đủ
9. GET /jobs/{id}/stream (SSE)
10. POST /jobs/{id}/cancel
11. Admin Endpoints (/admin/*)  ← MỚI
12. GET /health & GET /metrics
13. Webhook System  ← MỚI (schema đầy đủ)
14. n8n Integration Guide  ← MỚI
15. Payload Reference đầy đủ (tất cả operations)
16. Mã lỗi HTTP
17. Environment Variables Reference  ← MỚI
```

**Bổ sung so với hiện tại**:
- Timestamps fields: `created_at`, `started_at`, `finished_at`, `updated_at`
- `log` field trong JobResponse
- Webhook payload schema chi tiết
- Admin endpoints docs (5 endpoints)
- n8n guide với HTTP Request node JSON config
- Env vars table (17 biến từ `.env.example`)
- Port 6666 xuyên suốt

---

#### [NEW] `API_REFERENCE_EN.md` — Tiếng Anh
Cùng cấu trúc 17 sections nhưng viết bằng tiếng Anh hoàn toàn. Đây là file cho:
- Cộng tác viên quốc tế
- Import vào n8n (read documentation)
- Chia sẻ công khai

---

#### [NEW] `openapi.yaml` — OpenAPI 3.1 Spec
**Import được vào**: Postman, Insomnia, n8n HTTP Request node (schema), Swagger UI  
**Cấu trúc**:
```yaml
openapi: 3.1.0
info:
  title: AI Video Engine API
  version: "2.0"
  description: ...
servers:
  - url: http://localhost:6666
    description: Local development
  - url: https://{domain}
    description: Production (custom domain)
    variables:
      domain:
        default: your-server.com
securitySchemes:
  ApiKeyHeader:
    type: apiKey
    in: header
    name: X-API-Key
  BearerAuth:
    type: http
    scheme: bearer

paths:
  /health: GET
  /metrics: GET
  /jobs: POST + GET
  /jobs/upload: POST
  /jobs/{job_id}: GET
  /jobs/{job_id}/stream: GET (SSE)
  /jobs/{job_id}/cancel: POST
  /admin: GET
  /admin/jobs: GET
  /admin/jobs/{job_id}/assets: GET
  /admin/events: GET
  /admin/jobs/{job_id}/cleanup: DELETE

components/schemas:
  - CreateJobRequest
  - JobResponse (với tất cả fields kể cả timestamps)
  - JobListResponse
  - CancelJobResponse
  - JobError
  - ResultItem
  - WebhookPayload (schema webhook POST)
  - ProviderConfig
  - Operation (low_level)
```

---

## 🔢 Thứ Tự Thực Thi

| # | Việc làm | File | Type | Ưu tiên |
|---|---|---|---|---|
| 1 | Đổi port 6666 trong `.env.example` | `.env.example` | MODIFY | 🔴 |
| 2 | Test webhook dispatch | `tests/test_webhook_dispatch.py` | NEW | 🔴 |
| 3 | Test admin routes | `tests/test_admin_routes.py` | NEW | 🔴 |
| 4 | Test upload flow | `tests/test_api_upload.py` | NEW | 🔴 |
| 5 | Test n8n payload compat | `tests/test_n8n_payload_compat.py` | NEW | 🔴 |
| 6 | Test rate limiter | `tests/test_rate_limit.py` | NEW | 🟡 |
| 7 | Test Supabase repo | `tests/test_supabase_repo.py` | NEW | 🟡 |
| 8 | Live smoke test script | `scripts/test_api_live.py` | NEW | 🟡 |
| 9 | Webhook e2e script | `scripts/test_webhook_live.py` | NEW | 🟡 |
| 10 | **Viết lại API_REFERENCE.md** (VI) | `API_REFERENCE.md` | OVERWRITE | 🔴 |
| 11 | **Tạo API_REFERENCE_EN.md** (EN) | `API_REFERENCE_EN.md` | NEW | 🔴 |
| 12 | **Tạo openapi.yaml** | `openapi.yaml` | NEW | 🔴 |
| 13 | Chạy `pytest tests/ -v` full suite | CLI | RUN | 🔴 |

---

## 📐 Phạm Vi Kỹ Thuật

### Về Test Supabase
Sẽ dùng **mock client** (không cần Supabase thực khi chạy CI), nhưng tạo hướng dẫn:
```bash
# Để test với Supabase thực (integration)
SUPABASE_URL=https://xxx.supabase.co \
SUPABASE_KEY=service-role-key \
JOB_BACKEND=supabase \
pytest tests/test_supabase_repo.py -v --integration
```

### Về openapi.yaml vs .md
Cả hai đều cần vì:
- **openapi.yaml**: Import vào Postman/n8n, tự động generate client SDK, CI validation
- **API_REFERENCE.md**: Đọc trên GitHub, hướng dẫn step-by-step, có diagram

### Về n8n Integration
Sẽ có section riêng trong docs với:
1. Cấu hình **HTTP Request Node** (POST /jobs)
2. Cấu hình **Webhook Trigger Node** (nhận callback)
3. **Error Handling** (IF node check status=failed)
4. Ví dụ workflow JSON (có thể import vào n8n)

---

## ✅ Tiêu Chí Hoàn Thành

- [ ] `pytest tests/ -v` pass 100% (bao gồm test mới)
- [ ] `openapi.yaml` valid (qua `openapi-spec-validator`)
- [ ] `API_REFERENCE.md` có đủ 17 sections, port 6666
- [ ] `API_REFERENCE_EN.md` đầy đủ tương đương bản VI
- [ ] `scripts/test_api_live.py` có thể chạy với server live
- [ ] `scripts/test_webhook_live.py` test webhook e2e thành công
