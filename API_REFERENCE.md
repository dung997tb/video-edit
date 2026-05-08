# 📡 API Reference — AI Video Automation Engine

> **Base URL:** `http://localhost:8000`  
> **Auth Header:** `X-API-Key: <your-secret-key>`  
> **Content-Type:** `application/json`

---

## 🔐 Xác Thực (Authentication)

Tất cả các endpoints đều yêu cầu header xác thực:

```
X-API-Key: your-secret-key
```

Giá trị key được khai báo trong `.env` ở biến `API_SECRET_KEY`.

---

## 📋 Danh Sách Endpoints

| Method | Endpoint | Mô tả |
|---|---|---|
| `POST` | `/jobs` | Tạo Job mới từ URL hoặc source_key |
| `POST` | `/jobs/upload` | Tạo Job từ file upload trực tiếp |
| `GET` | `/jobs` | Lấy danh sách Jobs |
| `GET` | `/jobs/{job_id}` | Lấy thông tin 1 Job |
| `GET` | `/jobs/{job_id}/stream` | Theo dõi tiến độ realtime (SSE) |
| `POST` | `/jobs/{job_id}/cancel` | Hủy Job đang chạy |
| `GET` | `/metrics` | Prometheus metrics endpoint |
| `GET` | `/health` | Kiểm tra sức khỏe server |

---

## 📌 POST `/jobs` — Tạo Job Mới

Tạo một job xử lý video mới từ URL hoặc file đã có trên artifact store.

### Request Body

```json
{
  "pipeline_type": "dubbing",
  "input_uri": "https://example.com/video.mp4",
  "source_key": null,
  "source_sha256": null,
  "input_path": null,
  "priority": 0,
  "payload": {
    "target_language": "vi",
    "source_language": "auto",
    "tts_voice": "vi-VN-HoaiMyNeural",
    "output_name": "my-custom-folder"
  },
  "metadata": {
    "project": "campaign-spring-2026"
  }
}
```

| Field | Kiểu | Bắt buộc | Mô tả |
|---|---|---|---|
| `pipeline_type` | `string` | ✅ | Loại pipeline: `dubbing`, `subtitle`, `audio_extract`, `multilang_dubbing`, `ad_video`, `low_level` |
| `input_uri` | `string` | ⚠️ (1 trong 3) | URL video nguồn (`http://`, `https://`) |
| `source_key` | `string` | ⚠️ (1 trong 3) | Key của file đã có trên artifact store |
| `input_path` | `string` | ⚠️ (1 trong 3) | Đường dẫn local (chỉ khi `API_ALLOW_INPUT_PATH=true`) |
| `source_sha256` | `string` | ❌ | Hash để xác minh nội dung video |
| `priority` | `int` | ❌ | Ưu tiên trong hàng đợi (mặc định: `0`) |
| `payload` | `object` | ❌ | Các tham số điều chỉnh pipeline (xem bảng payload bên dưới) |
| `metadata` | `object` | ❌ | Dữ liệu tùy chỉnh, được lưu theo job |

### Response `201 Created`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "pipeline_type": "dubbing",
  "priority": 0,
  "source_sha256": "a1b2c3d4...",
  "input_uri": "https://example.com/video.mp4",
  "output_path": null,
  "pid": null,
  "worker_id": null,
  "cancel_requested": false,
  "attempt_count": 0,
  "progress": 0,
  "step_index": 0,
  "total_steps": 0,
  "current_step": null,
  "error": null,
  "error_detail": null,
  "metadata": { "project": "campaign-spring-2026" }
}
```

### Ví dụ cURL

```bash
curl -X POST http://localhost:8000/jobs \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline_type": "dubbing",
    "input_uri": "https://example.com/video.mp4",
    "payload": {
      "target_language": "vi",
      "output_name": "du-an-mua-he"
    }
  }'
```

---

## 📤 POST `/jobs/upload` — Upload File & Tạo Job

Upload file video trực tiếp và tạo job trong cùng một request. Hỗ trợ streaming upload, an toàn với file lớn.

### Request (multipart/form-data)

| Field | Kiểu | Bắt buộc | Mô tả |
|---|---|---|---|
| `file` | `file` | ✅ | File video cần xử lý |
| `pipeline_type` | `string` | ❌ | Mặc định: `dubbing` |
| `payload_json` | `string` (JSON) | ❌ | Payload dưới dạng chuỗi JSON |
| `metadata_json` | `string` (JSON) | ❌ | Metadata dưới dạng chuỗi JSON |

> **Giới hạn kích thước:** Mặc định 512MB (kiểm soát qua `API_UPLOAD_MAX_BYTES`).

### Ví dụ cURL

```bash
curl -X POST http://localhost:8000/jobs/upload \
  -H "X-API-Key: your-secret-key" \
  -F "file=@/path/to/video.mp4" \
  -F "pipeline_type=dubbing" \
  -F 'payload_json={"target_language":"vi","output_name":"video-thu"}'
```

### Ví dụ JavaScript (Fetch)

```javascript
const formData = new FormData();
formData.append('file', videoFile);
formData.append('pipeline_type', 'dubbing');
formData.append('payload_json', JSON.stringify({
  target_language: 'vi',
  tts_voice: 'vi-VN-HoaiMyNeural',
  output_name: 'my-video'
}));

const response = await fetch('http://localhost:8000/jobs/upload', {
  method: 'POST',
  headers: { 'X-API-Key': 'your-secret-key' },
  body: formData,
});
const job = await response.json();
console.log('Job ID:', job.id);
```

---

## 📄 GET `/jobs` — Danh Sách Jobs

### Query Parameters

| Param | Kiểu | Mô tả |
|---|---|---|
| `status` | `string` | Lọc theo trạng thái: `pending`, `running`, `done`, `failed`, `cancelled` |
| `limit` | `int` | Số lượng kết quả trả về (1–200, mặc định: 50) |

### Ví dụ cURL

```bash
# Lấy tất cả Jobs đang chạy
curl "http://localhost:8000/jobs?status=running&limit=20" \
  -H "X-API-Key: your-secret-key"
```

### Response

```json
{
  "items": [
    { "id": "...", "status": "running", "progress": 45, ... },
    { "id": "...", "status": "running", "progress": 72, ... }
  ]
}
```

---

## 🔍 GET `/jobs/{job_id}` — Chi Tiết Job

### Response — Job thành công

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "done",
  "pipeline_type": "dubbing",
  "progress": 100,
  "step_index": 6,
  "total_steps": 6,
  "current_step": "final",
  "output_path": "output/du-an-mua-he/final.mp4",
  "error": null,
  "error_detail": null
}
```

### Response — Job thất bại (có `error_detail`)

```json
{
  "id": "...",
  "status": "failed",
  "error": "command failed with code 1: ffmpeg ...",
  "error_detail": {
    "code": "FFMPEG_FAILED",
    "message": "command failed...",
    "step": "burned_video",
    "retriable": true
  }
}
```

### Bảng `error_detail.code`

| Code | Bước xảy ra | Có thể retry? |
|---|---|---|
| `FFMPEG_FAILED` | Bất kỳ bước nào dùng FFmpeg | ✅ |
| `TRANSCRIPTION_FAILED` | `transcript` | ✅ |
| `TRANSLATION_FAILED` | `translate` | ✅ |
| `TTS_FAILED` | `tts` | ✅ |
| `VOICE_SYNC_FAILED` | `synced_audio` | ✅ |
| `INPUT_NOT_FOUND` | Khởi tạo pipeline | ❌ |
| `CANCELLED` | Bất kỳ | ❌ |
| `UNKNOWN` | Không xác định | ✅ |

---

## 📡 GET `/jobs/{job_id}/stream` — Realtime Progress (SSE)

Kết nối Server-Sent Events để nhận cập nhật tiến độ từng giây một.

### Ví dụ JavaScript

```javascript
const eventSource = new EventSource(
  `http://localhost:8000/jobs/${jobId}/stream`,
  { headers: { 'X-API-Key': 'your-secret-key' } }
);

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`Progress: ${data.progress}% | Step: ${data.current_step}`);
  
  if (['done', 'failed', 'cancelled'].includes(data.status)) {
    console.log('Final status:', data.status);
    eventSource.close();
  }
};
```

### SSE Event Payload

```json
{
  "id": "550e8400-...",
  "status": "running",
  "progress": 66,
  "step_index": 4,
  "total_steps": 6,
  "current_step": "synced_audio",
  "error": null,
  "error_detail": null
}
```

> **Lưu ý cho Nginx:** Đảm bảo set header `X-Accel-Buffering: no` và `Cache-Control: no-cache` ở reverse proxy để tránh buffer làm trễ event.

---

## ⛔ POST `/jobs/{job_id}/cancel` — Hủy Job

Gửi tín hiệu hủy cho Job đang chạy. Worker sẽ kết thúc an toàn trong vòng `CANCEL_GRACE_SECONDS` giây.

### Response

```json
{
  "id": "550e8400-...",
  "cancel_requested": true,
  "status": "running"
}
```

### Ví dụ cURL

```bash
curl -X POST "http://localhost:8000/jobs/550e8400-.../cancel" \
  -H "X-API-Key: your-secret-key"
```

---

## 📊 GET `/metrics` — Prometheus Metrics

Trả về dữ liệu metrics định dạng Prometheus text format.

```bash
curl http://localhost:8000/metrics
```

**Các metrics quan trọng:**

| Metric | Loại | Mô tả |
|---|---|---|
| `job_submitted_total` | Counter | Tổng số job đã tạo (theo `pipeline_type`) |
| `job_completed_total` | Counter | Tổng số job hoàn thành |
| `job_failed_total` | Counter | Tổng số job thất bại |
| `active_jobs` | Gauge | Số job đang chạy hiện tại |

---

## ❌ Mã Lỗi HTTP

| HTTP Code | Ý nghĩa |
|---|---|
| `400 Bad Request` | Input không hợp lệ (pipeline type không tồn tại, URI không hợp lệ...) |
| `401 Unauthorized` | Thiếu hoặc sai `X-API-Key` |
| `404 Not Found` | Job ID không tồn tại |
| `413 Request Entity Too Large` | File upload vượt quá giới hạn |
| `429 Too Many Requests` | Vượt quá rate limit (mặc định 60 req/phút) |
| `500 Internal Server Error` | Lỗi nội bộ server |

---

## 🎛️ Payload Reference Đầy Đủ

Các key có thể dùng trong `payload` của bất kỳ pipeline nào:

| Key | Kiểu | Mô tả |
|---|---|---|
| `target_language` | `string` | Ngôn ngữ đích (`vi`, `en`, `ja`, `ko`, `zh`, ...) |
| `source_language` | `string` | Ngôn ngữ nguồn (`auto` để tự nhận dạng) |
| `tts_voice` | `string` | Tên giọng đọc (phụ thuộc `tts_engine`) |
| `tts_engine` | `string` | `edge-tts` / `openai` / `google-cloud` |
| `tts_rate` | `string` | Tốc độ đọc: `+10%`, `-20%` (mặc định `+0%`) |
| `tts_volume` | `string` | Âm lượng: `+5%` (mặc định `+0%`) |
| `tts_parallel_workers` | `int` | Số luồng TTS song song (mặc định: `1`) |
| `burn_subtitle` | `bool` | Gắn cứng phụ đề lên video (mặc định: `false`) |
| `target_languages` | `string[]` | Dành cho `multilang_dubbing`: danh sách ngôn ngữ |
| `output_name` | `string` | Tên thư mục output tùy chỉnh (thay vì UUID) |
| `cache_bust` | `bool` | `true` để bỏ qua toàn bộ cache (mặc định: `false`) |
| `normalize_loudness` | `bool` | Chuẩn hóa âm lượng (dành cho `audio_extract`) |
| `ad_text` | `string` | Kịch bản text (dành cho `ad_video`) |

### Danh Sách Giọng Đọc Edge-TTS (Phổ biến)

| Giọng | Ngôn ngữ | Giới tính |
|---|---|---|
| `vi-VN-HoaiMyNeural` | Tiếng Việt | Nữ |
| `vi-VN-NamMinhNeural` | Tiếng Việt | Nam |
| `en-US-JennyNeural` | Tiếng Anh (Mỹ) | Nữ |
| `en-US-GuyNeural` | Tiếng Anh (Mỹ) | Nam |
| `ja-JP-NanamiNeural` | Tiếng Nhật | Nữ |
| `ko-KR-SunHiNeural` | Tiếng Hàn | Nữ |
| `zh-CN-XiaoxiaoNeural` | Tiếng Trung | Nữ |
