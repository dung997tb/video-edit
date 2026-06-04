# n8n-nodes-ai-video-engine

Community nodes for **Mewocamm Video Editor**.

Mewocamm Video Editor là backend xử lý video bất đồng bộ qua FastAPI. Package này giúp n8n tạo job, upload video, chờ kết quả, hủy job và nhận callback mà không phải tự dựng HTTP Request node cho từng workflow.

> Tương thích ngược: trước đây node/package dùng tên **AI Video Engine**. Internal node names vẫn giữ `aiVideoEngine`, `aiVideoEngineTrigger` và credential `aiVideoEngineApi` để workflow cũ không bị gãy.

## Nodes

- **Mewocamm Video Editor**: node chính để tạo job, upload file, lấy trạng thái, chờ kết quả, hủy job và chạy preset pipeline.
- **Mewocamm Video Editor Trigger**: trigger nhận callback `job.completed`, `job.failed`, `job.cancelled`.

## Credentials

Tạo credential **Mewocamm Video Editor API** trong n8n:

| Field | Giá trị ví dụ | Ghi chú |
|---|---|---|
| **Base URL** | `http://localhost:6666` hoặc `http://host.docker.internal:6666` | URL backend Mewocamm |
| **Authentication Type** | `X-API-Key Header` | Hoặc `Bearer Token` |
| **API Key** | `your-secret-key` | Khớp `API_SECRET_KEY` của backend |

Credential test gọi `GET /jobs?limit=1`. Nếu test pass thì node có thể xác thực với các operation chính.

## Action Node Operations

### Resource: Job

- **Create Custom**: tạo job bằng `pipeline_type` và `Payload JSON` tự viết.
- **Upload And Create**: upload binary data từ node trước rồi tạo job qua `/jobs/upload`.
- **Get**: lấy thông tin một job theo `Job ID`.
- **List**: liệt kê job, có thể lọc theo status.
- **Cancel**: gửi yêu cầu hủy job.
- **Wait**: polling cho đến khi job `done`, `failed` hoặc `cancelled`.

### Resource: Preset Pipeline

- **Low Level Edit**: cắt, scale, reframe, split screen hoặc operations JSON.
- **Dubbing**: lồng tiếng/dịch giọng.
- **Subtitle**: tạo phụ đề hoặc burn phụ đề vào video.
- **Silence Cut**: cắt khoảng lặng.
- **Extract Audio**: tách audio.
- **Extract Frames**: trích xuất frame ảnh.

Các operation tạo job đều có **Advanced Payload JSON** để merge thêm field backend-specific mà không cần release node mới.

## Output

Mọi operation trả raw job response kèm các field đã normalize:

- `job_id`
- `status`
- `progress`
- `current_step`
- `output_path`
- `result_items`
- `error`
- `error_detail`

**Output Mode** có thể trả toàn bộ job hoặc tách thành một n8n item cho mỗi entry trong `metadata.result_items[]`.

Binary result download chưa có trong V1 vì backend hiện chưa expose public output download route hoặc signed artifact URL. Khi backend có route như `GET /outputs/{job_id}/{file}`, node có thể thêm toggle `Download Result to Binary`.

## Long Jobs

**Wait** dùng polling và giữ một execution worker của n8n trong lúc render. Với job dài, nên dùng callback:

1. Tạo job với `webhook_url`.
2. Dùng **Mewocamm Video Editor Trigger** để nhận callback.

## Docker Networking

Khi n8n chạy Docker nhưng API chạy native trên host, dùng:

```text
http://host.docker.internal:6666
```

Khi n8n và API cùng một Docker network, dùng service name:

```text
http://api:6666
```

## Local Development

```bash
cd n8n-nodes-ai-video-engine
npm install
npm run build
npm test
```

Chạy node trong n8n local:

```bash
npm run dev
```

Fallback thủ công:

```bash
npm run build
npm link
cd ~/.n8n/custom
npm link n8n-nodes-ai-video-engine
```

Restart n8n sau khi link.

## Release Checks

```bash
npm run build
npm run lint
npm test
npm pack --dry-run
```

## Public Docs

- `docs/API_GUIDE.vi.md`: hướng dẫn gọi API backend Mewocamm.
- `docs/N8N_CUSTOM_NODES_GUIDE.vi.md`: hướng dẫn dùng node trong n8n.
- `docs/N8N_REAL_VIDEO_MANUAL_TESTS.md`: hướng dẫn/evidence test bằng video thật.
