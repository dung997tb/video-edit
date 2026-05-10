# 🤖 Kế Hoạch Workflow n8n — Test Toàn Bộ Pipeline Trên Video Thực
## AI Video Engine — n8n Integration Test Suite

> **n8n URL**: http://localhost:5678  
> **API URL**: http://localhost:6666  
> **Video test**: `test.mp4` (19.9MB) · `test_input.mp4` (12MB)  
> **Chiến lược**: Mỗi workflow = 1 pipeline type, có kiểm tra kết quả tự động

---

## 📐 Kiến Trúc Tổng Thể

```
n8n Workflow Suite
├── WF-MASTER     → Điều phối chạy tất cả test theo thứ tự
├── WF-HELPER     → Webhook receiver (nhận callback từ API)
│
├── GROUP A — Video Processing (low_level)
│   ├── WF-01  Cut + Speed + Flip
│   ├── WF-02  Portrait Reframe (1080×1920)
│   ├── WF-03  Split Screen (HStack)
│   ├── WF-04  TikTok Split Screen
│   └── WF-05  Audio Operations
│
├── GROUP B — AI Features
│   ├── WF-06  Dubbing EN→VI
│   ├── WF-07  Subtitle Generation
│   ├── WF-08  Silence Cut
│   └── WF-09  Audio Extract
│
├── GROUP C — Advanced AI
│   ├── WF-10  Ad Video (TTS + burn subtitle)
│   ├── WF-11  Auto B-Roll
│   ├── WF-12  Face Track Portrait
│   └── WF-13  Semantic Edit
│
└── GROUP D — Pipeline Orchestration
    ├── WF-14  Split Video (clip chunks)
    ├── WF-15  Extract Frames
    ├── WF-16  Workflow DAG
    └── WF-17  Batch Multi-Video (4 videos song song)
```

---

## 🔧 Cấu Hình Chung (Áp dụng cho tất cả WF)

### n8n Credential Setup
```
Vào Settings → Credentials → Add Credential → Header Auth
Name  : Video API Key
Name  : X-API-Key
Value : [API_SECRET_KEY từ .env]
```

### Biến môi trường n8n
```
Vào Settings → Variables:
VIDEO_API_URL  = http://localhost:6666
VIDEO_TEST_MP4 = http://localhost:6666/uploads/test_input.mp4  (nếu dùng upload trước)
```

### Pattern Chung: Poll-Based Job Runner
> Dùng cho tất cả workflow. Gồm 5 nodes chuẩn:

```
[Manual Trigger]
    ↓
[HTTP Request] POST /jobs  →  lưu job_id
    ↓
[Loop] (Split In Batches với 1 item):
  [HTTP Request] GET /jobs/{{$json.job_id}}
  [IF] status ∈ {done, failed, cancelled}
      → TRUE: exit loop
      → FALSE: [Wait 3s] → quay lại loop
    ↓
[IF] status == "done"
    → TRUE:  [Set] lấy output_path + result_items → [Respond OK]
    → FALSE: [Set] lấy error_detail → [Respond FAIL]
```

---

## 📋 Chi Tiết Từng Workflow

---

### WF-HELPER — Webhook Receiver (cài trước)

**Mục đích**: Nhận POST callback từ API khi job hoàn thành. Dùng chung cho tất cả WF có webhook.

```
[Webhook Trigger] path=video-callback
  Method: POST
    ↓
[Switch] event:
  job.completed → [Set] output = result_items
  job.failed    → [Set] error = error_detail
  job.cancelled → [Set] status = cancelled
    ↓
[Respond to Webhook] HTTP 204
    ↓
[Slack/Email] Thông báo (tuỳ chọn)
```

**Webhook URL sinh ra**: `http://localhost:5678/webhook/video-callback`

---

### WF-01 — Cut + Speed + Flip

**Pipeline**: `low_level`  
**Mục tiêu**: Video 8s cắt còn 5s, tăng tốc x1.2, lật ngang

**Node: Create Job (HTTP Request)**
```json
POST http://localhost:6666/jobs
Header: X-API-Key = {{$env.VIDEO_API_KEY}}
Body:
{
  "pipeline_type": "low_level",
  "input_path": "test_input.mp4",
  "payload": {
    "output_name": "n8n-wf01-{{$now.toMillis()}}",
    "operations": [
      {"type": "cut",   "params": {"start": 0, "duration": 5}},
      {"type": "speed", "params": {"factor": 1.2}},
      {"type": "flip",  "params": {"mode": "horizontal"}}
    ]
  }
}
```

**PASS criteria**:
- [ ] HTTP 200, `id` có trong response
- [ ] Sau poll: `status == "done"`
- [ ] `metadata.result_items[0].media_type == "video"`

---

### WF-02 — Portrait Reframe 1080×1920

**Pipeline**: `low_level`  
**Mục đích**: Chuyển video ngang sang dọc 9:16 với blur background

**Body**:
```json
{
  "pipeline_type": "low_level",
  "input_path": "test_input.mp4",
  "payload": {
    "output_name": "n8n-wf02-portrait",
    "operations": [
      {"type": "blur_bg_portrait", "params": {"output_width": 1080, "output_height": 1920}},
      {"type": "pad_border",       "params": {"size": 10, "color": "#000000"}},
      {"type": "auto_zoom",        "params": {"interval_seconds": 5}}
    ]
  }
}
```

**PASS criteria**:
- [ ] `status == "done"`
- [ ] Output resolution 1080×1920 (verify bằng ffprobe nếu cần)

---

### WF-03 — Split Screen HStack

**Pipeline**: `low_level`  
**Mục đích**: 2 video side-by-side 1280×720

**Body**:
```json
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
          "output_height": 720
        }
      }
    ]
  }
}
```

**PASS criteria**:
- [ ] `status == "done"`, output 1280×720

---

### WF-04 — TikTok Split Screen

**Pipeline**: `low_level`  
**Mục đích**: Video portrait top/bottom split, mix audio

**Body**:
```json
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
          "audio_source": "mix"
        }
      }
    ]
  }
}
```

**PASS criteria**:
- [ ] `status == "done"`, có audio track

---

### WF-05 — Audio Operations

**Pipeline**: `low_level`  
**Mục đích**: Tăng pitch, normalize, fade-in

**Body**:
```json
{
  "pipeline_type": "low_level",
  "input_path": "test_input.mp4",
  "payload": {
    "output_name": "n8n-wf05-audio",
    "operations": [
      {"type": "audio_pitch",     "params": {"semitones": 2, "preserve_tempo": true}},
      {"type": "audio_normalize", "params": {}},
      {"type": "audio_fade",      "params": {"type": "in", "duration": 0.5}},
      {"type": "audio_volume",    "params": {"volume": 0.9}}
    ]
  }
}
```

---

### WF-06 — Dubbing EN→VI

**Pipeline**: `dubbing`  
**Mục đích**: Dịch và lồng tiếng Việt với giọng HoaiMy

> ⚠️ Yêu cầu Whisper model đã tải xuống

**Body**:
```json
{
  "pipeline_type": "dubbing",
  "input_path": "test_input.mp4",
  "payload": {
    "source_language": "en",
    "target_language": "vi",
    "translator_service": "google",
    "tts_voice": "vi-VN-HoaiMyNeural",
    "tts_rate": "-5%",
    "webhook_url": "http://localhost:5678/webhook/video-callback"
  }
}
```

**Pattern**: Webhook-based (không poll, dùng WF-HELPER nhận callback)  
**Timeout**: 10 phút (Whisper + TTS)  
**PASS criteria**:
- [ ] WF-HELPER nhận `event=job.completed`
- [ ] Output có audio track tiếng Việt

---

### WF-07 — Subtitle Generation

**Pipeline**: `subtitle`  
**Mục đích**: Tạo phụ đề tự động, burn vào video

**Body**:
```json
{
  "pipeline_type": "subtitle",
  "input_path": "test_input.mp4",
  "payload": {
    "language": "auto",
    "burn_subtitle": true,
    "font_size": 28,
    "font_color": "white",
    "stroke_color": "black",
    "stroke_width": 2
  }
}
```

**PASS criteria**:
- [ ] `status == "done"`, output có phụ đề

---

### WF-08 — Silence Cut

**Pipeline**: `silence_cut`  
**Mục đích**: Tự động xóa khoảng im lặng

**Body**:
```json
{
  "pipeline_type": "silence_cut",
  "input_path": "test_input.mp4",
  "payload": {
    "min_silence_duration": 0.3,
    "silence_threshold_db": -35,
    "output_name": "n8n-wf08-silence-cut"
  }
}
```

**PASS criteria**:
- [ ] `status == "done"`, duration output < duration input

---

### WF-09 — Audio Extract

**Pipeline**: `audio-extract`  
**Mục đích**: Tách audio thành file WAV riêng

**Body**:
```json
{
  "pipeline_type": "audio-extract",
  "input_path": "test_input.mp4",
  "payload": {
    "format": "wav",
    "sample_rate": 44100
  }
}
```

**PASS criteria**:
- [ ] `status == "done"`, `result_items[0].media_type == "audio"`

---

### WF-10 — Ad Video (TTS + Subtitle)

**Pipeline**: `ad_video`  
**Mục đích**: Tạo video quảng cáo với TTS tiếng Việt và phụ đề

**Body**:
```json
{
  "pipeline_type": "ad_video",
  "input_path": "test.mp4",
  "payload": {
    "ad_text": "Sản phẩm chất lượng cao, giá tốt nhất thị trường. Đặt hàng ngay hôm nay!",
    "tts_voice": "vi-VN-HoaiMyNeural",
    "tts_engine": "edge-tts",
    "burn_subtitle": true
  }
}
```

**PASS criteria**:
- [ ] `status == "done"`, output có audio TTS tiếng Việt

---

### WF-11 — Auto B-Roll

**Pipeline**: `auto_broll`  
**Mục đích**: Tự động ghép b-roll vào video chính

**Body**:
```json
{
  "pipeline_type": "auto_broll",
  "input_path": "test.mp4",
  "payload": {
    "broll_source": "test_input.mp4",
    "insert_interval": 10,
    "broll_duration": 3
  }
}
```

---

### WF-12 — Face Track Portrait

**Pipeline**: `face_track_portrait`  
**Mục đích**: Tự động theo dõi khuôn mặt, crop dọc

**Body**:
```json
{
  "pipeline_type": "face_track_portrait",
  "input_path": "test_input.mp4",
  "payload": {
    "output_width": 1080,
    "output_height": 1920,
    "smooth_factor": 0.8
  }
}
```

---

### WF-13 — Semantic Edit (Silence Cut)

**Pipeline**: `semantic_edit`  
**Mục đích**: AI-driven edit với câu lệnh ngôn ngữ tự nhiên

**Body**:
```json
{
  "pipeline_type": "semantic_edit",
  "input_path": "test_input.mp4",
  "payload": {
    "command": "silence_cut",
    "min_silence_duration": 0.3,
    "silence_threshold_db": -35
  }
}
```

---

### WF-14 — Split Video

**Pipeline**: `split_video`  
**Mục đích**: Cắt video thành nhiều clip theo thời gian

**Body**:
```json
{
  "pipeline_type": "split_video",
  "input_path": "test.mp4",
  "payload": {
    "segment_duration": 30,
    "output_prefix": "clip"
  }
}
```

**PASS criteria**:
- [ ] `result_items` có nhiều items (> 1)

---

### WF-15 — Extract Frames

**Pipeline**: `extract_frames`  
**Mục đích**: Xuất các frame từ video thành ảnh

**Body**:
```json
{
  "pipeline_type": "extract_frames",
  "input_path": "test_input.mp4",
  "payload": {
    "fps": 1,
    "format": "jpg",
    "max_frames": 10
  }
}
```

**PASS criteria**:
- [ ] `result_items` có ≥ 10 items, `media_type == "image"`

---

### WF-16 — Workflow DAG (Multi-step)

**Pipeline**: `workflow`  
**Mục đích**: Chạy pipeline nhiều bước theo graph dependency

**Body**:
```json
{
  "pipeline_type": "workflow",
  "input_path": "test_input.mp4",
  "payload": {
    "workflow": {
      "nodes": {
        "cut": {
          "type": "video.cut",
          "params": {"start": 0, "end": 15}
        },
        "scale": {
          "type": "video.scale",
          "params": {"width": 1080, "height": 1920},
          "depends_on": ["cut"]
        },
        "border": {
          "type": "video.pad_border",
          "params": {"size": 10, "color": "white"},
          "depends_on": ["scale"]
        },
        "export": {
          "type": "media.finalize",
          "depends_on": ["border"]
        }
      }
    }
  }
}
```

---

### WF-17 — Batch Multi-Video (4 videos song song)

**Mục đích**: Test throughput: tạo 4 jobs đồng thời, theo dõi tất cả đến khi xong

**Thiết kế n8n**:
```
[Manual Trigger]
    ↓
[Code] Tạo array 4 payloads khác nhau
    ↓
[Split In Batches] (batch size 1)
    ↓
[HTTP Request] POST /jobs (tạo job cho từng item)
    ↓
[Merge] Tập hợp tất cả job_ids
    ↓
[Loop] Poll tất cả jobs:
  [HTTP Request] GET /admin/jobs
  [IF] tất cả status ∈ terminal → EXIT
  [Wait 3s]
    ↓
[Code] Tính summary: pass/fail/time
    ↓
[Respond] Report
```

**PASS criteria**:
- [ ] 4/4 jobs đều `status == "done"`
- [ ] `admin/jobs` hiển thị đúng

---

## 🛠️ Script Tự Động Import Workflow vào n8n

> Xem file `scripts/setup_n8n_workflows.py` để tạo các workflow tự động qua n8n REST API.

```bash
# Bước 1: Lấy API key từ n8n
# Vào n8n → Settings → API → Create API Key → copy

# Bước 2: Chạy script
python scripts/setup_n8n_workflows.py \
  --n8n-url http://localhost:5678 \
  --n8n-api-key YOUR_N8N_API_KEY \
  --video-api-url http://localhost:6666 \
  --video-api-key YOUR_VIDEO_API_KEY
```

---

## 📊 Bảng Theo Dõi Tiến Độ

| Workflow | Pipeline | Độ phức tạp | AI cần | Trạng thái |
|---|---|:---:|:---:|:---:|
| WF-01 Cut+Speed+Flip | low_level | ⭐ | ❌ | ⬜ Chưa chạy |
| WF-02 Portrait | low_level | ⭐⭐ | ❌ | ⬜ Chưa chạy |
| WF-03 HStack | low_level | ⭐ | ❌ | ⬜ Chưa chạy |
| WF-04 TikTok Split | low_level | ⭐ | ❌ | ⬜ Chưa chạy |
| WF-05 Audio Ops | low_level | ⭐ | ❌ | ⬜ Chưa chạy |
| WF-06 Dubbing | dubbing | ⭐⭐⭐ | ✅ Whisper+TTS | ⬜ Chưa chạy |
| WF-07 Subtitle | subtitle | ⭐⭐ | ✅ Whisper | ⬜ Chưa chạy |
| WF-08 Silence Cut | silence_cut | ⭐⭐ | ✅ VAD | ⬜ Chưa chạy |
| WF-09 Audio Extract | audio-extract | ⭐ | ❌ | ⬜ Chưa chạy |
| WF-10 Ad Video | ad_video | ⭐⭐⭐ | ✅ TTS | ⬜ Chưa chạy |
| WF-11 Auto B-Roll | auto_broll | ⭐⭐ | ❌ | ⬜ Chưa chạy |
| WF-12 Face Track | face_track_portrait | ⭐⭐ | ✅ CV | ⬜ Chưa chạy |
| WF-13 Semantic Edit | semantic_edit | ⭐⭐ | ✅ | ⬜ Chưa chạy |
| WF-14 Split Video | split_video | ⭐ | ❌ | ⬜ Chưa chạy |
| WF-15 Extract Frames | extract_frames | ⭐ | ❌ | ⬜ Chưa chạy |
| WF-16 Workflow DAG | workflow | ⭐⭐⭐ | ❌ | ⬜ Chưa chạy |
| WF-17 Batch 4-jobs | low_level×4 | ⭐⭐ | ❌ | ⬜ Chưa chạy |
| WF-HELPER Webhook | receiver | ⭐ | ❌ | ⬜ Chưa setup |

---

## 🗂️ Thứ Tự Thực Hiện Đề Xuất

```
NGÀY 1 — Cài đặt & Group A (FFmpeg thuần)
  ├── Setup: n8n credential, WF-HELPER
  ├── WF-01, WF-02, WF-03, WF-04, WF-05
  └── Xác nhận: 5/5 PASS

NGÀY 2 — Group B (AI Features)
  ├── WF-06 Dubbing (cần Whisper)
  ├── WF-07 Subtitle
  ├── WF-08 Silence Cut
  └── WF-09 Audio Extract

NGÀY 3 — Group C + D (Advanced + Orchestration)
  ├── WF-10, WF-11, WF-12, WF-13
  ├── WF-14, WF-15, WF-16
  └── WF-17 Batch test

NGÀY 4 — Integration & Production
  └── Chạy toàn bộ bằng WF-MASTER
```
