# Hướng dẫn API Mewocamm Video Editor

Tài liệu này mô tả cách gọi API backend hiện tại của **Mewocamm Video Editor**. API đang theo mô hình **job-first**: client tạo job, backend xử lý bất đồng bộ, client poll hoặc nhận callback.

## 1. Kết nối và xác thực

Base URL local mặc định:

```text
http://localhost:6666
```

Khi n8n chạy Docker còn API chạy trên host:

```text
http://host.docker.internal:6666
```

Header xác thực:

```http
X-API-Key: <API_SECRET_KEY>
```

Hoặc:

```http
Authorization: Bearer <API_SECRET_KEY>
```

## 2. Tạo job

Endpoint:

```http
POST /jobs
```

Body chung:

```json
{
  "pipeline_type": "low_level",
  "input_uri": "https://example.com/input.mp4",
  "payload": {},
  "metadata": {
    "case": "demo"
  },
  "priority": 0
}
```

Các nguồn input portable:

- `input_uri`: URL HTTP/HTTPS backend có thể tải.
- `source_key`: artifact key đã có trong storage.
- `input_path`: chỉ dùng nội bộ/dev khi backend cho phép.

Response quan trọng:

```json
{
  "id": "job-123",
  "status": "pending",
  "progress": 0,
  "output_path": null,
  "metadata": {}
}
```

## 3. Ví dụ pipeline

### Cắt và scale video

```json
{
  "pipeline_type": "low_level",
  "input_uri": "https://example.com/input.mp4",
  "payload": {
    "operations": [
      {"type": "cut", "params": {"start": 0, "duration": 5}},
      {"type": "scale", "params": {"width": 1080, "height": 1920}}
    ],
    "output_name": "demo_cut_scale"
  }
}
```

### Lồng tiếng

```json
{
  "pipeline_type": "dubbing",
  "input_uri": "https://example.com/input.mp4",
  "payload": {
    "source_language": "auto",
    "target_language": "vi",
    "translator": "google",
    "tts_voice": "vi-VN-HoaiMyNeural",
    "tts_rate": "-5%"
  }
}
```

### Phụ đề

```json
{
  "pipeline_type": "subtitle",
  "input_uri": "https://example.com/input.mp4",
  "payload": {
    "language": "auto",
    "burn_subtitle": true,
    "style": {
      "font_size": 28,
      "font_color": "white",
      "stroke_color": "black",
      "stroke_width": 2
    }
  }
}
```

### Cắt khoảng lặng

```json
{
  "pipeline_type": "silence_cut",
  "input_uri": "https://example.com/input.mp4",
  "payload": {
    "min_silence_duration": 0.3,
    "silence_threshold_db": -35
  }
}
```

### Tách audio

```json
{
  "pipeline_type": "audio-extract",
  "input_uri": "https://example.com/input.mp4",
  "payload": {
    "format": "wav",
    "sample_rate": 44100
  }
}
```

### Trích xuất frame

```json
{
  "pipeline_type": "extract_frames",
  "input_uri": "https://example.com/input.mp4",
  "payload": {
    "fps": 1,
    "format": "jpg",
    "max_frames": 10
  }
}
```

## 4. Upload rồi tạo job

Endpoint:

```http
POST /jobs/upload
```

Form fields:

- `file`: file video binary.
- `pipeline_type`: ví dụ `low_level`.
- `payload_json`: JSON string cho payload.
- `metadata_json`: JSON string cho metadata.

Node n8n **Mewocamm Video Editor** dùng endpoint này trong operation **Upload And Create**.

## 5. Theo dõi job

Lấy một job:

```http
GET /jobs/{job_id}
```

Liệt kê job:

```http
GET /jobs?status=running&limit=50
```

Hủy job:

```http
POST /jobs/{job_id}/cancel
```

Các trạng thái chính:

- `pending`: job đang chờ.
- `running`: worker đang xử lý.
- `done`: job hoàn tất.
- `failed`: job lỗi.
- `cancelled`: job bị hủy.

## 6. Callback webhook

Khi tạo job, thêm `webhook_url` trong payload nếu muốn backend gọi về n8n:

```json
{
  "pipeline_type": "low_level",
  "input_uri": "https://example.com/input.mp4",
  "payload": {
    "webhook_url": "https://n8n.example/webhook/mewocamm-video-callback",
    "operations": [
      {"type": "cut", "params": {"start": 0, "duration": 5}}
    ]
  }
}
```

Callback event mà trigger n8n đang hỗ trợ:

- `job.completed`
- `job.failed`
- `job.cancelled`

## 7. Output contract

Client nên đọc artifact qua các field sau:

```json
{
  "id": "job-123",
  "status": "done",
  "output_path": "output/demo/final.mp4",
  "metadata": {
    "result_items": [
      {
        "path": "output/demo/final.mp4",
        "media_type": "video"
      }
    ]
  }
}
```

Quy tắc cho n8n:

- Dùng `job_id` để wait/get/cancel.
- Dùng `output_path` cho output chính.
- Dùng `metadata.result_items[]` khi pipeline tạo nhiều artifact như audio/frame/subtitle.
- V1 chưa có signed download URL hoặc public binary download route.

## 8. Ghi chú về VideoDB

VideoDB dùng API thiên về resource-first như collection, video, audio, image và timeline. Mewocamm Video Editor hiện dùng job-first API để tối ưu xử lý video bất đồng bộ, retry, cancel và evidence test. Nếu sau này cần UX giống VideoDB hơn, phase sau nên thêm asset/resource API ổn định trước rồi mới expose thành node n8n riêng.
