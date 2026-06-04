# Hướng dẫn Custom Node n8n cho Mewocamm Video Editor

Tài liệu này hướng dẫn cài đặt và dùng package `n8n-nodes-ai-video-engine` trong n8n.

Package hiện có 2 node:

- **Mewocamm Video Editor**: node chính để tạo job, upload file, lấy trạng thái, chờ kết quả, hủy job và chạy các preset video.
- **Mewocamm Video Editor Trigger**: webhook trigger để nhận callback `job.completed`, `job.failed`, `job.cancelled`.

> Tương thích ngược: trước đây package hiển thị tên **AI Video Engine**. Internal node names vẫn là `aiVideoEngine`, `aiVideoEngineTrigger` và credential `aiVideoEngineApi` để workflow cũ tiếp tục chạy.

## 1. Điều kiện trước khi dùng

Backend Mewocamm Video Editor cần chạy và truy cập được từ n8n.

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

Khi n8n chạy Docker còn API chạy native trên host, Base URL trong credential nên là:

```text
http://host.docker.internal:6666
```

## 2. Cài đặt

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

Với n8n Docker trong dev, có thể copy package đã build vào container rồi restart:

```powershell
docker exec n8n mkdir -p /home/node/.n8n/nodes/node_modules
docker cp ./n8n-nodes-ai-video-engine n8n:/home/node/.n8n/nodes/node_modules/n8n-nodes-ai-video-engine
docker restart n8n
```

Khi publish npm chính thức, nên cài qua UI `Settings -> Community Nodes`.

## 3. Tạo credential

Tạo credential loại **Mewocamm Video Editor API**.

| Trường | Giá trị ví dụ | Ghi chú |
|---|---|---|
| Base URL | `http://host.docker.internal:6666` | URL backend Mewocamm từ n8n |
| Authentication Type | `X-API-Key Header` | Hoặc `Bearer Token` |
| API Key | `your-secret-key` | Khớp `API_SECRET_KEY` |

Credential test gọi:

```http
GET /jobs?limit=1
```

Nếu test pass, các operation chính có thể xác thực.

## 4. Node Mewocamm Video Editor

Node này dùng khi workflow cần gọi API xử lý video.

### Resource: Job

#### Create Custom

Dùng khi bạn muốn tự viết payload pipeline.

Input quan trọng:

- `Pipeline Type`: ví dụ `low_level`, `dubbing`, `subtitle`, `silence_cut`, `audio-extract`, `extract_frames`.
- `Source Mode`: chọn `Input URI` hoặc `Source Key`.
- `Payload JSON`: cấu hình xử lý video gửi vào backend.
- `Advanced Payload JSON`: merge thêm field nâng cao vào payload.
- `Metadata JSON`: thông tin truy vết workflow/test/user.

Ví dụ payload:

```json
{
  "operations": [
    {"type": "cut", "params": {"start": 0, "duration": 5}},
    {"type": "scale", "params": {"width": 1080, "height": 1920}}
  ]
}
```

Output trả về job đã normalize, gồm `job_id`, `status`, `output_path`, `result_items`, `error`, `error_detail`.

#### Upload And Create

Dùng khi node trước đó có binary data, ví dụ nhận file từ form hoặc tải file từ URL.

Input quan trọng:

- `Binary Property`: tên binary property chứa file, mặc định `data`.
- `Pipeline Type`.
- `Payload JSON`.

Node gửi multipart form tới `/jobs/upload`.

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

Poll job cho đến khi trạng thái là `done`, `failed` hoặc `cancelled`.

Input quan trọng:

- `Poll Interval Seconds`: số giây giữa mỗi lần kiểm tra.
- `Timeout Seconds`: thời gian chờ tối đa.
- `Fail on Failed or Cancelled`: bật để workflow fail khi job lỗi/bị hủy.

Lưu ý: polling giữ execution worker của n8n. Với render dài, nên dùng **Mewocamm Video Editor Trigger**.

### Resource: Preset Pipeline

#### Low Level Edit

Dùng cho cắt ghép cơ bản và thao tác FFmpeg.

Template có sẵn:

- `Cut And Scale`: cắt đoạn video rồi scale.
- `Portrait Reframe`: đổi sang khung dọc.
- `Split Screen HStack`: ghép hai video cạnh nhau.
- `Split Screen`: ghép video chính và B-roll.
- `Audio Operations`: thao tác pitch/fade/volume mẫu.
- `Custom JSON`: tự viết mảng `operations`.

#### Dubbing

Dùng để lồng tiếng/dịch giọng.

Input chính:

- `Source Language`: ngôn ngữ gốc, có thể dùng `auto`.
- `Target Language`: ngôn ngữ đầu ra, ví dụ `vi`.
- `Translator Service`: dịch vụ dịch.
- `TTS Voice`: giọng đọc.
- `TTS Rate`: tốc độ đọc.

#### Subtitle

Dùng để tạo phụ đề hoặc burn phụ đề vào video.

Input chính:

- `Language`: ngôn ngữ phụ đề, có thể dùng `auto`.
- `Burn Subtitle`: bật để đóng cứng phụ đề lên video.
- `Font Size`, `Font Color`, `Stroke Color`, `Stroke Width`: style phụ đề.

#### Silence Cut

Dùng để cắt đoạn im lặng.

Input chính:

- `Minimum Silence Duration`: khoảng im lặng tối thiểu.
- `Silence Threshold DB`: ngưỡng âm lượng để xem là im lặng.

#### Extract Audio

Dùng để tách audio từ video.

Input chính:

- `Audio Format`: `wav`, `mp3`, `m4a`.
- `Sample Rate`: ví dụ `44100`.

#### Extract Frames

Dùng để trích xuất frame ảnh.

Input chính:

- `FPS`: số frame mỗi giây.
- `Image Format`: `jpg`, `png`, `webp`.
- `Max Frames`: giới hạn số frame.

## 5. Node Mewocamm Video Editor Trigger

Node này dùng để nhận callback từ backend thay vì polling.

Input:

- `Path`: đường dẫn webhook, mặc định `mewocamm-video-callback`.
- `Events`: chọn event được phép kích hoạt workflow.

Events hỗ trợ:

- `job.completed`
- `job.failed`
- `job.cancelled`

Workflow gợi ý:

1. Tạo workflow bắt đầu bằng **Mewocamm Video Editor Trigger**.
2. Copy production webhook URL.
3. Khi tạo job, truyền URL đó vào `payload.webhook_url`.
4. Backend gọi lại n8n khi job kết thúc.

## 6. Output Mode

`Output Mode = Job` trả về một item chứa job:

```json
{
  "job_id": "job-123",
  "status": "done",
  "output_path": "output/demo/final.mp4",
  "result_items": []
}
```

`Output Mode = Result Items` trả về một item cho mỗi artifact trong `metadata.result_items[]`.

V1 chưa tải binary trực tiếp vì backend chưa có public output route/signed URL.

## 7. Test nhanh trong n8n

Search trong palette:

- `Mewocamm`
- `AI Video Engine`
- `lồng tiếng`
- `phụ đề`
- `cắt video`

Các từ khóa trên đều phải tìm được node nhờ alias.

Workflow smoke:

```text
Manual Trigger -> Mewocamm Video Editor (Create Custom) -> Mewocamm Video Editor (Wait)
```

Payload smoke:

```json
{
  "operations": [
    {"type": "cut", "params": {"start": 0, "duration": 5}}
  ],
  "output_name": "n8n_smoke_cut_5s"
}
```

## 8. Kiểm tra package trước khi release

```bash
cd n8n-nodes-ai-video-engine
npm run build
npm run lint
npm test
npm pack --dry-run
```
