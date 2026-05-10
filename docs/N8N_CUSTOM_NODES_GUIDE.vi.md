# Hướng dẫn Custom Node n8n cho AI Video Engine

Tài liệu này hướng dẫn cài đặt và sử dụng package `n8n-nodes-ai-video-engine`.

Package gồm 2 node:

- `AI Video Engine`: node thao tác chính để tạo job, upload file, lấy trạng thái, chờ kết quả, hủy job, và dùng preset pipeline.
- `AI Video Engine Trigger`: webhook trigger để nhận callback `job.completed`, `job.failed`, `job.cancelled`.

## 1. Điều kiện trước khi dùng

AI Video Engine API cần chạy và truy cập được từ n8n.

Ví dụ local:

```bash
python main.py api
curl http://localhost:6666/health
```

Nếu bật xác thực:

```env
API_AUTH_ENABLED=true
API_SECRET_KEY=your-secret-key
```

Nếu muốn dùng callback webhook:

```env
WEBHOOKS_ENABLED=true
WEBHOOK_TIMEOUT_SECONDS=10
```

Khi n8n và API chạy ở hai container hoặc hai máy khác nhau, không dùng `localhost` nếu nó trỏ sai container. Hãy dùng hostname Docker network, private IP, hoặc domain HTTPS thật.

## 2. Cài đặt

### Cài từ npm community node

Trong n8n self-hosted:

1. Vào `Settings` -> `Community Nodes`.
2. Chọn `Install`.
3. Nhập `n8n-nodes-ai-video-engine`.
4. Cài đặt và restart n8n nếu n8n yêu cầu.

### Cài local để phát triển

```bash
cd n8n-nodes-ai-video-engine
npm install
npm run build
npm test
```

Chạy n8n local bằng node CLI:

```bash
npm run dev
```

Fallback thủ công:

```bash
cd n8n-nodes-ai-video-engine
npm run build
npm link

mkdir -p ~/.n8n/custom
cd ~/.n8n/custom
npm link n8n-nodes-ai-video-engine
```

Sau đó restart n8n.

### Docker/self-hosted

Với n8n Docker, cách ổn định nhất là cài community node trong UI. Nếu build image riêng, cài package vào thư mục custom của n8n rồi restart container.

Ví dụ ý tưởng:

```Dockerfile
FROM n8nio/n8n:latest
USER node
RUN mkdir -p /home/node/.n8n/custom
WORKDIR /home/node/.n8n/custom
RUN npm install n8n-nodes-ai-video-engine
```

## 3. Tạo credential

Tạo credential loại `AI Video Engine API`.

| Trường | Giá trị ví dụ | Ghi chú |
|---|---|---|
| Base URL | `http://localhost:6666` | URL của FastAPI service |
| Authentication Type | `X-API-Key` | Hoặc `Bearer` |
| API Key | `your-secret-key` | Khớp `API_SECRET_KEY` |

Credential test gọi:

```http
GET /jobs?limit=1
```

Vì đây là endpoint protected, nếu credential test pass thì các operation chính cũng có thể xác thực.

## 4. Node AI Video Engine

### Resource: Job

#### Create Custom

Dùng khi bạn muốn tự viết payload pipeline.

Trường quan trọng:

- `Pipeline Type`: ví dụ `low_level`, `dubbing`, `subtitle`, `silence_cut`, `audio-extract`, `extract_frames`
- `Source Mode`: `Input URI` hoặc `Source Key`
- `Payload JSON`: payload gửi vào API
- `Advanced Payload JSON`: merge đè lên payload
- `Metadata JSON`: metadata job
- `Priority`: độ ưu tiên job

Ví dụ payload:

```json
{
  "operations": [
    {"type": "cut", "params": {"start": 0, "duration": 5}},
    {"type": "scale", "params": {"width": 1080, "height": 1920}}
  ]
}
```

#### Upload And Create

Dùng khi node trước đó có binary data, ví dụ tải file từ URL hoặc nhận file qua form.

Trường quan trọng:

- `Binary Property`: mặc định `data`
- `Pipeline Type`
- `Payload JSON`

Node gửi multipart form:

- `file`
- `pipeline_type`
- `payload_json`
- `metadata_json`

API sẽ lưu file vào artifact store và thêm `source_key` vào payload.

#### Get

Nhập `Job ID`, node gọi:

```http
GET /jobs/{job_id}
```

#### List

Liệt kê job:

```http
GET /jobs?status=running&limit=50
```

`Status = Any` sẽ không gửi filter.

#### Cancel

Gọi:

```http
POST /jobs/{job_id}/cancel
```

#### Wait

Poll job cho đến khi trạng thái là:

- `done`
- `failed`
- `cancelled`

Mặc định:

- `Poll Interval Seconds`: `15`
- `Timeout Seconds`: `900`
- `Fail on Failed or Cancelled`: bật

Lưu ý: polling giữ execution worker của n8n trong lúc chờ. Với video dài 15-30 phút, nên dùng webhook trigger thay vì Wait.

### Resource: Preset Pipeline

#### Low Level Edit

Các template có sẵn:

- `Cut And Scale`
- `Portrait Reframe`
- `Split Screen HStack`
- `Split Screen`
- `Audio Operations`
- `Custom JSON`

`Custom JSON` cần object có mảng `operations`.

```json
{
  "operations": [
    {"type": "cut", "params": {"start": 0, "duration": 5}},
    {"type": "flip", "params": {"mode": "horizontal"}}
  ]
}
```

#### Dubbing

Tạo job `dubbing`.

Trường chính:

- `Source Language`
- `Target Language`
- `Translator Service`
- `TTS Voice`
- `TTS Rate`
- `Webhook URL`

Ví dụ giọng Việt:

```text
vi-VN-HoaiMyNeural
```

#### Subtitle

Tạo job `subtitle`.

Trường chính:

- `Language`
- `Burn Subtitle`
- `Font Size`
- `Font Color`
- `Stroke Color`
- `Stroke Width`

#### Silence Cut

Tạo job `silence_cut`.

Trường chính:

- `Minimum Silence Duration`
- `Silence Threshold DB`

#### Extract Audio

Tạo job `audio-extract`.

Trường chính:

- `Audio Format`: `wav`, `mp3`, `m4a`
- `Sample Rate`

#### Extract Frames

Tạo job `extract_frames`.

Trường chính:

- `FPS`
- `Image Format`
- `Max Frames`

## 5. Node AI Video Engine Trigger

Trigger tạo một webhook URL trong n8n. Dùng URL này làm `webhook_url` trong payload job.

Events hỗ trợ:

- `job.completed`
- `job.failed`
- `job.cancelled`

Output chuẩn:

```json
{
  "event": "job.completed",
  "job_id": "JOB_ID",
  "status": "done",
  "output_path": "output/job/final.mp4",
  "result_items": [],
  "error": null,
  "error_detail": null
}
```

## 6. Workflow mẫu

### Upload file -> tạo job -> chờ done

1. `HTTP Request` tải video, bật response binary.
2. `AI Video Engine`
   - Resource: `Job`
   - Operation: `Upload And Create`
   - Binary Property: `data`
   - Pipeline Type: `low_level`
   - Payload JSON:

```json
{
  "operations": [
    {"type": "cut", "params": {"start": 0, "duration": 5}}
  ]
}
```

3. `AI Video Engine`
   - Resource: `Job`
   - Operation: `Wait`
   - Job ID: `{{$json.job_id}}`

### Low-level edit từ URL

1. `AI Video Engine`
   - Resource: `Preset Pipeline`
   - Operation: `Low Level Edit`
   - Source Mode: `Input URI`
   - Input URI: `{{$json.video_url}}`
   - Operation Template: `Cut And Scale`

2. Tùy nhu cầu, thêm node `Wait`.

### Dubbing bằng webhook

1. `AI Video Engine Trigger`
   - Path: `ai-video-engine-callback`
   - Events: chọn cả 3 event.

2. Copy production webhook URL của trigger.

3. Trong workflow tạo job:
   - `AI Video Engine`
   - Resource: `Preset Pipeline`
   - Operation: `Dubbing`
   - Webhook URL: URL vừa copy

Khi backend render xong, workflow trigger sẽ chạy.

### Subtitle

`AI Video Engine`:

- Resource: `Preset Pipeline`
- Operation: `Subtitle`
- Language: `auto`
- Burn Subtitle: bật

### Extract Frames

`AI Video Engine`:

- Resource: `Preset Pipeline`
- Operation: `Extract Frames`
- FPS: `1`
- Image Format: `jpg`
- Max Frames: `10`

## 7. Output và file kết quả

V1 trả về:

- `output_path`
- `metadata.result_items`
- `result_items`

Chưa tải file kết quả về binary data trong n8n vì backend hiện chưa có route public download hoặc signed URL.

Để hỗ trợ use-case "render video -> upload YouTube/Google Drive/TikTok", backend nên thêm một trong hai cách:

- route tải file như `GET /outputs/{job_id}/{filename}`
- signed artifact URL trong `result_items`

Khi đó node có thể thêm tùy chọn `Download Result to Binary Property`.

## 8. Troubleshooting

### Credential test báo 401

Kiểm tra:

- `API_AUTH_ENABLED=true`
- `API_SECRET_KEY` đúng
- Credential chọn đúng `X-API-Key` hoặc `Bearer`

### Lỗi 400 unsupported pipeline_type

Kiểm tra `Pipeline Type`. Các tên phổ biến:

- `low_level`
- `dubbing`
- `subtitle`
- `silence_cut`
- `audio-extract`
- `extract_frames`

### Lỗi 413 khi upload

File vượt `API_UPLOAD_MAX_BYTES`. Tăng biến môi trường backend:

```env
API_UPLOAD_MAX_BYTES=536870912
```

### Lỗi 429 rate limit

Giảm tần suất polling hoặc tăng:

```env
API_RATE_LIMIT_PER_MINUTE=200
```

Với workflow dài, dùng webhook thay vì Wait.

### Callback không tới n8n

Kiểm tra:

- `WEBHOOKS_ENABLED=true`
- URL webhook là production URL, không phải test URL hết hạn
- API server truy cập được domain n8n
- reverse proxy cho phép POST body JSON
- nếu chạy Docker, không dùng `localhost` sai container

### Wait bị timeout

Tăng `Timeout Seconds`, hoặc dùng webhook trigger cho render dài.
