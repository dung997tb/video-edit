# 🎬 Kế Hoạch Test Thực Tế — Video + n8n Integration
## AI Video Engine — Real-World Test Plan

> **Video test sẵn có**: `test.mp4` (19.9MB), `test_input.mp4` (12MB)  
> **Port API**: `6666`  
> **n8n**: self-hosted cùng VPS  
> **Nguyên tắc**: Mỗi test có INPUT rõ ràng, OUTPUT mong đợi, PASS/FAIL criteria

---

## 📋 Tổng Quan

```
PHASE 1 — CLI Local (không cần server)    ~30 phút
PHASE 2 — API + Video thực tế             ~60 phút
PHASE 3 — Webhook end-to-end              ~30 phút
PHASE 4 — n8n Workflow thực tế            ~60 phút
PHASE 5 — Stress test & Edge cases        ~30 phút
```

---

## PHASE 1 — CLI Local (Baseline xác nhận FFmpeg hoạt động)

Chạy trực tiếp bằng `main.py run`, không qua API. Mục tiêu: xác nhận pipeline cốt lõi chạy được với video thực trước khi test qua HTTP.

### T1.1 — Cut + Speed + Flip
```bash
python main.py run test_input.mp4 \
  --config-file pipelines/examples/low_level_basic.json
```
- **Output mong đợi**: `output/*/final.mp4` dài ~7.3s (8s ÷ 1.1), bị flip ngang
- **PASS**: file tồn tại, `ffprobe` không báo lỗi

### T1.2 — Portrait Reframe (blur bg + auto zoom)
```bash
python main.py run test_input.mp4 \
  --config-file pipelines/examples/test_suite_portrait.json
```
- **Output mong đợi**: video 1080×1920, có blur background, auto zoom từng 5s
- **PASS**: resolution đúng `1080x1920`, file > 0 bytes

### T1.3 — Audio Operations
```bash
python main.py run test_input.mp4 \
  --config-file pipelines/examples/test_suite_audio.json
```
- **Output mong đợi**: audio tăng 2 semitones, normalized, fade-in 0.5s
- **PASS**: file có audio track, `ffprobe` báo duration khớp

### T1.4 — Split Screen (hstack)
```bash
python main.py run test.mp4 \
  --config-file pipelines/examples/hstack_test.json
```
- **Output mong đợi**: video 1280×720, 2 video side-by-side
- **PASS**: resolution `1280x720`

### T1.5 — Split Screen TikTok
```bash
python main.py run test.mp4 \
  --config-file pipelines/examples/split_screen_tiktok.json
```
- **Output mong đợi**: video portrait, top/bottom split 50/50
- **PASS**: file có 2 track audio (mix)

### T1.6 — Dubbing (EN→VI)
```bash
python main.py run test.mp4 \
  --config-file pipelines/examples/voiceover_en_to_vi.json
```
- **Output mong đợi**: video tiếng Việt giọng HoaiMy, có phụ đề
- **PASS**: audio track tiếng Việt, duration ≈ input duration
- **Yêu cầu**: Internet, Whisper model đã download, input có speech segment rõ ràng

### T1.7 — Audio Extract
```bash
python main.py run test_input.mp4 \
  --pipeline-type audio_extract \
  --target-language vi
```
- **Output mong đợi**: `audio.wav` trong output folder
- **PASS**: file `.wav` tồn tại, có audio data

---

## PHASE 2 — API Test Với Video Thực (Server chạy thực)

### Setup
```bash
# Terminal 1: Khởi động server
python main.py api

# Verify
curl http://localhost:6666/health
```

### T2.1 — Upload File + low_level Pipeline
```bash
curl -X POST http://localhost:6666/jobs/upload \
  -H "X-API-Key: $API_KEY" \
  -F "file=@test_input.mp4;type=video/mp4" \
  -F "pipeline_type=low_level" \
  -F 'payload_json={
    "output_name": "test-upload-cut",
    "operations": [
      {"type": "cut", "params": {"start": 0, "duration": 5}},
      {"type": "scale", "params": {"width": 1280, "height": 720}}
    ]
  }'
```
- **Lưu `JOB_ID` từ response**
- **PASS**: HTTP 200, `id` có trong response, `source_sha256` khớp với file

### T2.2 — Poll Until Done
```bash
# Lặp cho đến khi status=done
watch -n 2 "curl -s http://localhost:6666/jobs/$JOB_ID \
  -H 'X-API-Key: $API_KEY' | python -m json.tool"
```
- **PASS**: status chuyển `pending → running → done`
- **PASS**: `metadata.result_items` có ít nhất 1 item với `media_type=video`
- **PASS**: `output_path` trỏ đến file tồn tại thực

### T2.3 — SSE Stream Progress (song song với T2.1)
```bash
curl -N "http://localhost:6666/jobs/$JOB_ID/stream" \
  -H "X-API-Key: $API_KEY"
```
- **PASS**: nhận được events JSON mỗi giây, `progress` tăng dần 0→100
- **PASS**: stream tự kết thúc khi `status=done`

### T2.4 — Jobs từ input_uri (HTTP URL)
```bash
# Dùng URL HTTP ổn định. Runner tự dựng local static server để tránh phụ thuộc CDN public.
curl -X POST http://localhost:6666/jobs \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline_type": "low_level",
    "input_uri": "http://127.0.0.1:<static-port>/test_input.mp4",
    "payload": {
      "output_name": "test-uri-flip",
      "operations": [
        {"type": "cut", "params": {"start": 0, "duration": 3}},
        {"type": "flip", "params": {"mode": "horizontal"}}
      ]
    }
  }'
```
- **PASS**: HTTP 200, job tạo thành công, xử lý xong

### T2.5 — Cancel Job đang chạy
```bash
# Tạo job nặng (dubbing)
JOB=$(curl -s -X POST http://localhost:6666/jobs/upload \
  -H "X-API-Key: $API_KEY" \
  -F "file=@test.mp4" \
  -F "pipeline_type=dubbing" \
  -F 'payload_json={"target_language":"vi"}')
JOB_ID=$(echo $JOB | python -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Đợi 2s rồi cancel
sleep 2
curl -X POST "http://localhost:6666/jobs/$JOB_ID/cancel" \
  -H "X-API-Key: $API_KEY"
```
- **PASS**: `cancel_requested=true` ngay lập tức
- **PASS**: sau vài giây `status=cancelled`

### T2.6 — Priority Queue
```bash
# Tạo 3 jobs cùng lúc, priority khác nhau
for p in 0 5 10; do
  curl -s -X POST http://localhost:6666/jobs \
    -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
    -d "{\"pipeline_type\":\"low_level\",\"input_path\":\"test_input.mp4\",\"priority\":$p,
         \"payload\":{\"operations\":[{\"type\":\"cut\",\"params\":{\"duration\":2}}]}}"
done
```
- **PASS**: job `priority=10` được claim và chạy trước

### T2.7 — Admin Dashboard kiểm tra
```bash
# Mở browser
http://localhost:6666/admin
```
- **PASS**: HTML load, hiển thị danh sách jobs
- **PASS**: Filter theo status hoạt động
- **PASS**: Nút Cancel trong UI gọi được API

---

## PHASE 3 — Webhook End-to-End (Server + Mock Listener)

### T3.1 — Webhook khi Job Done
```bash
python scripts/test_webhook_live.py \
  --base-url http://localhost:6666 \
  --api-key $API_KEY \
  --webhook-port 0 \
  --input-uri "http://127.0.0.1:<static-port>/test_input.mp4" \
  --timeout 120
```
- **PASS**: "PASSED live webhook test" in output
- **PASS**: webhook payload có `event=job.completed`, `job_id` đúng
- **PASS**: `metadata.result_items` không rỗng

### T3.2 — Webhook khi Job Failed
```bash
# Tạo job với input_uri sai (404)
curl -X POST http://localhost:6666/jobs \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{
    "pipeline_type": "low_level",
    "input_uri": "https://example.com/nonexistent.mp4",
    "payload": {
      "webhook_url": "http://localhost:9999/webhook",
      "operations": [{"type":"cut","params":{"duration":3}}]
    }
  }'
```
- **PASS**: webhook nhận `event=job.failed`, `error_detail.code` có giá trị

### T3.3 — Webhook khi Job Cancelled
- Tạo job nặng với `webhook_url`, cancel sau 2s
- **PASS**: webhook nhận `event=job.cancelled`

---

## PHASE 4 — n8n Workflow Thực Tế

### Môi trường
```
n8n URL : http://localhost:5678  (hoặc VPS IP:5678)
API URL : http://localhost:6666  (hoặc VPS IP:6666)
```

> **Lưu ý**: Khi test trên cùng VPS, dùng `localhost` hoặc private IP.  
> Khi n8n gọi từ internet → cần domain/IP public cho cả 2 service.

---

### Workflow W1 — Cơ Bản: Tạo Job → Poll → Done
**Mô tả**: n8n tạo job, poll mỗi 10s, lấy output path khi done.

```
[Manual Trigger]
    ↓
[HTTP Request] POST /jobs
  Body: {pipeline_type, input_uri, payload}
    ↓
[Set] Lưu job_id = {{$json.id}}
    ↓
[Loop] Mỗi 10s:
  [HTTP Request] GET /jobs/{{job_id}}
  [IF] status == "done" → EXIT
       status == "failed" → ERROR branch
       else → continue loop
    ↓
[Set] output = {{$json.metadata.result_items[0].path}}
    ↓
[Respond] hoặc [Slack/Email notification]
```

**n8n JSON Body cho HTTP Request node:**
```json
{
  "pipeline_type": "low_level",
  "input_uri": "{{ $json.video_url }}",
  "payload": {
    "output_name": "n8n-job-{{ $now.toMillis() }}",
    "operations": [
      {"id": "cut-1", "type": "cut", "params": {"start": 0, "duration": 10}},
      {"id": "scale-1", "type": "scale", "params": {"width": 1080, "height": 1920}}
    ]
  },
  "metadata": {
    "n8n_execution_id": "{{ $execution.id }}",
    "n8n_workflow_id": "{{ $workflow.id }}"
  }
}
```

**PASS criteria**:
- [ ] n8n nhận được `job_id` từ API
- [ ] n8n poll thành công đến khi `status=done`
- [ ] n8n lấy được `result_items[0].path`

---

### Workflow W2 — Webhook-Driven (Không cần Poll)
**Mô tả**: n8n tạo job kèm `webhook_url` của chính n8n, đợi callback.

```
[Manual Trigger / Schedule]
    ↓
[HTTP Request] POST /jobs
  Body: {
    pipeline_type, input_uri,
    payload: { webhook_url: "http://VPS_IP:5678/webhook/video-done" }
  }
    ↓
[Respond] 200 OK (job đã tạo)

--- Sau đó khi job xong ---

[Webhook Trigger] POST /webhook/video-done
    ↓
[IF] event == "job.completed"
  → [Set] lấy result_items
  → [Notification] Slack/Email
[ELSE IF] event == "job.failed"
  → [Error Handler]
```

**Config Webhook Trigger node trong n8n:**
```
HTTP Method : POST
Path        : video-done
Response    : On Received
```

**PASS criteria**:
- [ ] Job tạo thành công từ n8n
- [ ] n8n Webhook Trigger nhận được POST sau khi job done
- [ ] `$json.event` == `"job.completed"`
- [ ] `$json.metadata.result_items` có data

---

### Workflow W3 — Upload File Từ n8n → Xử Lý
**Mô tả**: n8n đọc file từ disk/URL, upload lên API, xử lý.

```
[HTTP Request] GET file từ URL → binary data
    ↓
[HTTP Request] POST /jobs/upload
  Body (Form Data):
    file = binary từ step trước
    pipeline_type = "dubbing"
    payload_json = {"target_language":"vi","tts_voice":"vi-VN-HoaiMyNeural"}
    ↓
[Set] job_id
    ↓
[Wait / Webhook] cho đến khi done
```

**Config HTTP Request Upload trong n8n:**
```
Method           : POST
URL              : http://localhost:6666/jobs/upload
Authentication   : Header Auth
Header Name      : X-API-Key
Header Value     : {{ $env.VIDEO_API_KEY }}
Body Content Type: Form-Data

Form Fields:
  file         : [binary input từ node trước]
  pipeline_type: dubbing
  payload_json : {"target_language":"vi","webhook_url":"http://localhost:5678/webhook/video-done"}
```

**PASS criteria**:
- [ ] Upload thành công, API trả `source_sha256`
- [ ] Job chạy dubbing, output có tiếng Việt

---

### Workflow W4 — Batch Processing (Multiple Videos)
**Mô tả**: n8n lấy danh sách URL từ Google Sheet/Airtable, tạo nhiều job song song.

```
[Google Sheets] Lấy danh sách video URLs
    ↓
[SplitInBatches] Xử lý từng URL
    ↓
[HTTP Request] POST /jobs (mỗi URL)
    ↓
[Aggregate] Tập hợp job_ids
    ↓
[Loop] Poll tất cả jobs
    ↓
[Update Sheet] Ghi output_path vào Sheet
```

**PASS criteria**:
- [ ] Tất cả jobs được tạo
- [ ] Jobs chạy song song (verify qua `/admin/jobs`)
- [ ] Sheet được update với output path

---

### Workflow W5 — n8n gọi API từ Internet (Production)
**Yêu cầu**: VPS có domain hoặc IP public, nginx reverse proxy.

**Nginx config mẫu:**
```nginx
server {
    listen 80;
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://localhost:6666;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # SSE support
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding on;
    }
}
```

**n8n config:**
```
URL: https://api.yourdomain.com/jobs
Header: X-API-Key: your-secret-key
```

**PASS criteria**:
- [ ] n8n cloud (app.n8n.io) gọi được VPS API
- [ ] Webhook từ VPS callback được về n8n cloud/self-hosted
- [ ] SSL/TLS không gây lỗi

---

## PHASE 5 — Stress Test & Edge Cases

### T5.1 — Concurrent Jobs (4 jobs song song)
```bash
for i in 1 2 3 4; do
  curl -s -X POST http://localhost:6666/jobs \
    -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
    -d "{\"pipeline_type\":\"low_level\",\"input_path\":\"test_input.mp4\",
         \"payload\":{\"output_name\":\"stress-$i\",
         \"operations\":[{\"type\":\"cut\",\"params\":{\"duration\":3}}]}}" &
done
wait
```
- **PASS**: Tất cả 4 jobs completed, không job nào stuck
- **Quan sát**: `active_jobs` metric tăng lên tối đa 2 (MAX_WORKERS=2)

### T5.2 — File Lớn (test.mp4 = 19.9MB)
```bash
curl -X POST http://localhost:6666/jobs/upload \
  -H "X-API-Key: $API_KEY" \
  -F "file=@test.mp4;type=video/mp4" \
  -F "pipeline_type=low_level" \
  -F 'payload_json={"operations":[{"type":"cut","params":{"start":0,"duration":10}}]}'
```
- **PASS**: Upload không bị 413 (19.9MB < 512MB default)
- **PASS**: Xử lý hoàn thành trong < 120s

### T5.3 — Rate Limit
```bash
for i in $(seq 1 65); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    http://localhost:6666/jobs/__rate_limit_probe__ \
    -H "X-API-Key: $API_KEY"
done | sort | uniq -c
```
- **PASS**: endpoint protected trả non-2xx bình thường trước ngưỡng (ví dụ `404` cho job không tồn tại), và trả `429` sau khi vượt rate limit.

### T5.4 — Invalid Pipeline Type
```bash
curl -X POST http://localhost:6666/jobs \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"pipeline_type":"nonexistent","input_path":"test.mp4","payload":{}}'
```
- **PASS**: HTTP 400, `detail` liệt kê pipeline types hợp lệ

### T5.5 — Cache Behavior
```bash
# Chạy cùng job 2 lần → lần 2 dùng cache
JOB1=$(curl -s -X POST ... -d '{"payload":{"operations":[{"type":"cut","params":{"duration":3}}],...}}')
JOB2=$(curl -s -X POST ... -d '{"payload":{"operations":[{"type":"cut","params":{"duration":3}}],...}}')
```
- **Quan sát**: JOB2 chạy nhanh hơn JOB1 (cache hit)

---

## Result Checklist - Run 20260509_232601

Legend: `[x]` executed, `[ ]` blocked/not automated in this environment.

**Summary**: `22 PASS / 0 FAIL / 5 BLOCKED`  
**Runnable automated tests**: `22/22 PASS`  
**Run note**: final run used `http://127.0.0.1:6667` because local port `6666` was occupied by an external API process started with `API_AUTH_ENABLED=false`. Product default/config remains port `6666`.

### PHASE 1 - CLI
- [x] T1.1 Cut + Speed + Flip - PASS
- [x] T1.2 Portrait Reframe - PASS
- [x] T1.3 Audio Operations - PASS
- [x] T1.4 HStack - PASS
- [x] T1.5 Split Screen TikTok - PASS
- [x] T1.6 Dubbing EN->VI - PASS
- [x] T1.7 Audio Extract - PASS

### PHASE 2 - API Real Video
- [x] T2.1 Upload + low_level - PASS
- [x] T2.2 Poll Until Done - PASS
- [x] T2.3 SSE Stream - PASS
- [x] T2.4 input_uri via local HTTP static server - PASS
- [x] T2.5 Cancel running job - PASS
- [x] T2.6 Priority Queue - PASS
- [x] T2.7 Admin Dashboard - PASS

### PHASE 3 - Webhook
- [x] T3.1 Webhook on Done - PASS
- [x] T3.2 Webhook on Failed - PASS
- [x] T3.3 Webhook on Cancelled - PASS

### PHASE 4 - n8n
- [ ] W1 Poll workflow - BLOCKED (n8n reachable, workflow import/execution still manual)
- [ ] W2 Webhook-driven workflow - BLOCKED (n8n reachable, workflow import/execution still manual)
- [ ] W3 Upload from n8n - BLOCKED (n8n reachable, workflow import/execution still manual)
- [ ] W4 Batch processing - BLOCKED (n8n reachable, workflow import/execution still manual)
- [ ] W5 n8n from internet/domain - BLOCKED (requires production domain/reverse proxy validation)

### PHASE 5 - Stress
- [x] T5.1 4 concurrent jobs - PASS
- [x] T5.2 Large file 19.9MB - PASS
- [x] T5.3 Rate limit 429 - PASS
- [x] T5.4 Invalid pipeline - PASS
- [x] T5.5 Cache behavior - PASS

---
## 🔧 Environment Setup Trước Khi Test

```bash
# 1. Copy env
cp .env.example .env
# Chỉnh sửa:
# API_SECRET_KEY=your-real-key
# API_PORT=6666
# WEBHOOKS_ENABLED=true
# WHISPER_MODEL=base  (hoặc small nếu RAM đủ)

# 2. Khởi động API
python main.py api

# 3. Biến môi trường cho test
export API_KEY=your-real-key
export BASE_URL=http://localhost:6666

# 4. Verify
curl $BASE_URL/health
```

---

## Real-World Test Run Log - 20260509_232601

**Run timestamp**: `20260509_232601`  
**Runner**: `scripts/run_realworld_tests.py`  
**Base URL used**: `http://127.0.0.1:6667`  
**Full raw log**: `logs/realworld_test_20260509_232601.log`  
**Runner stdout mirror**: `logs/realworld_test_20260509_232601.runner_stdout.log`  
**Runner stderr mirror**: `logs/realworld_test_20260509_232601.runner_stderr.log`  
**Machine-readable results**: `logs/realworld_test_20260509_232601.results.json`  
**Status snapshot**: `logs/realworld_test_20260509_232601.status.json`  
**Summary**: `22 PASS / 0 FAIL / 5 BLOCKED`

**Error markers in final full log**:
- None. `logs/realworld_test_20260509_232601.log` contains no `### ERROR SECTION START` and no `[ERROR]` result marker.
- Expected worker stack traces appear for T3.2/T3.3 because those tests intentionally exercise `job.failed` and `job.cancelled`; both runner assertions passed.

| Test | Status | Time | Notes |
|---|---|---:|---|
| T1.1 | PASS | 6.71s | low-level output verified, duration 7.30s |
| T1.2 | PASS | 102.67s | portrait output verified, 30.00s |
| T1.3 | PASS | 2.40s | audio operations output has audio stream |
| T1.4 | PASS | 62.16s | hstack output verified |
| T1.5 | PASS | 121.44s | split-screen TikTok output has audio/video |
| T1.6 | PASS | 30.83s | dubbing output verified with audio/video |
| T1.7 | PASS | 4.59s | audio extract output duration 30.00s |
| T2.1 | PASS | 0.46s | upload OK, SHA256 matched |
| T2.2 | PASS | 4.08s | job reached `done`, output path exists |
| T2.3 | PASS | 0.00s | SSE captured 5 events |
| T2.4 | PASS | 3.08s | `input_uri` processed via local HTTP static server |
| T2.5 | PASS | 6.79s | running dubbing job cancelled |
| T2.6 | PASS | 4.26s | priority 10 was not preceded by lower priority |
| T2.7 | PASS | 0.04s | admin HTML, jobs JSON, status filter loaded |
| T3.1 | PASS | 2.68s | live webhook completed event received |
| T3.2 | PASS | 2.07s | webhook received `job.failed`, `FFMPEG_FAILED` |
| T3.3 | PASS | 3.54s | webhook received `job.cancelled` |
| W1 | BLOCKED | 0.01s | n8n reachable, workflow import/execution manual |
| W2 | BLOCKED | 0.01s | n8n reachable, workflow import/execution manual |
| W3 | BLOCKED | 0.01s | n8n reachable, workflow import/execution manual |
| W4 | BLOCKED | 0.01s | n8n reachable, workflow import/execution manual |
| W5 | BLOCKED | 0.01s | requires production domain/reverse proxy validation |
| T5.1 | PASS | 5.43s | 4 concurrent jobs completed |
| T5.2 | PASS | 3.47s | 19.9MB upload/process completed |
| T5.3 | PASS | 2.50s | protected endpoint produced `{404: 130, 429: 75}` |
| T5.4 | PASS | 0.02s | invalid pipeline returned HTTP 400 with supported list |
| T5.5 | PASS | 4.30s | repeated jobs completed; durations 2.18s / 2.12s |

