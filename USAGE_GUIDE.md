# 📖 Hướng Dẫn Sử Dụng — AI Video Automation Engine

> **Phiên bản:** Production-Grade v2.0 | **Ngôn ngữ:** Python 3.10+

---

## 1. 🛠️ Cài Đặt

### Bước 1 — Clone dự án & cài thư viện

```bash
git clone <repo-url>
cd video-edit
pip install -r requirements.txt
```

### Bước 2 — Cài đặt FFmpeg

**Windows:** Giải nén vào thư mục `tools/ffmpeg/`, sau đó khai báo đường dẫn trong `.env`:
```env
FFMPEG_PATH=tools\ffmpeg\ffmpeg-8.1-essentials_build\bin\ffmpeg.exe
FFPROBE_PATH=tools\ffmpeg\ffmpeg-8.1-essentials_build\bin\ffprobe.exe
```

**Linux / macOS:**
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS (Homebrew)
brew install ffmpeg
```
Trong `.env` để nguyên giá trị mặc định: `FFMPEG_PATH=ffmpeg`

### Bước 3 — Tạo file cấu hình

```bash
cp .env.example .env
```
Chỉnh sửa `.env` với các thông số thực tế của bạn (xem bảng cấu hình ở mục 3).

---

## 2. 🚀 Chạy Nhanh (Local CLI)

Cách đơn giản và nhanh nhất để thử hệ thống mà không cần cài database hay khởi động server:

### Lồng tiếng video từ tiếng Anh → tiếng Việt:
```bash
python main.py run video_goc.mp4 --target-language vi
```

### Chỉ tạo phụ đề không lồng tiếng:
```bash
python main.py run video_goc.mp4 --pipeline-type subtitle --target-language vi
```

### Lồng tiếng với giọng đọc tùy chỉnh:
```bash
python main.py run video_goc.mp4 --tts-voice vi-VN-NamMinhNeural --target-language vi
```

### Dùng file config JSON để điều chỉnh nâng cao:
```bash
python main.py run video_goc.mp4 --config-file pipelines/examples/low_level_basic.json
```

> **Lưu ý:** Ở chế độ Local CLI, hệ thống dùng bộ nhớ RAM (Memory backend) nên không cần cài Supabase. Kết quả xuất ra thư mục `output/{job_id}/final.mp4`.

---

## 3. ⚙️ Cấu Hình (.env)

### Bảng biến môi trường quan trọng:

| Biến | Mặc định | Mô tả |
|---|---|---|
| `JOB_BACKEND` | `memory` | Backend hàng đợi: `memory` (local) hoặc `supabase` (production) |
| `ARTIFACT_STORE_BACKEND` | `local` | Nơi lưu file: `local` hoặc `supabase` |
| `FFMPEG_PATH` | `ffmpeg` | Đường dẫn tới file thực thi ffmpeg |
| `WHISPER_MODEL` | `base` | Kích thước model Whisper: `tiny`, `base`, `small`, `medium`, `large` |
| `TRANSLATOR_SERVICE` | `google` | Dịch vụ dịch thuật: `google`, `deepl`, `libretranslate` |
| `TTS_ENGINE` | `edge-tts` | Bộ tổng hợp giọng đọc: `edge-tts`, `openai`, `google-cloud` |
| `TTS_DEFAULT_VOICE` | `vi-VN-HoaiMyNeural` | Tên giọng mặc định |
| `MAX_AUDIO_STRETCH` | `1.3` | Mức độ co/giãn tốc độ giọng đọc tối đa (1.3 = nhanh tối đa 30%) |
| `API_SECRET_KEY` | `change-me` | **⚠️ BẮT BUỘC đổi khi lên Production** |
| `API_EMBEDDED_WORKER` | `true` | `true`: Worker chạy cùng server. `false`: Chạy worker riêng |
| `API_RATE_LIMIT_PER_MINUTE` | `60` | Giới hạn request mỗi phút mỗi API key |
| `METRICS_ENABLED` | `true` | Bật endpoint `/metrics` cho Prometheus |

### Cấu hình Production (Supabase):
```env
JOB_BACKEND=supabase
ARTIFACT_STORE_BACKEND=supabase
API_EMBEDDED_WORKER=false
API_ALLOW_INPUT_PATH=false
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=your-service-role-key
SUPABASE_JOBS_TABLE=jobs
SUPABASE_STORAGE_BUCKET=artifacts
```

---

## 4. 🌐 Chạy API Server

```bash
# Khởi động server
python main.py api

# Hoặc chạy worker riêng biệt (khi API_EMBEDDED_WORKER=false)
python main.py api &
python main.py worker
```

Server sẽ lắng nghe tại `http://0.0.0.0:6666`. Truy cập `http://localhost:6666/docs` để xem Swagger UI.

### Xác thực (Authentication):
Mọi request cần header:
```
X-API-Key: <API_SECRET_KEY>
```

---

## 5. 🎬 Các Pipeline & Payload Options

Mỗi Job cần chọn một `pipeline_type` và cung cấp `payload` tương ứng:

### `dubbing` — Lồng tiếng đầy đủ
```json
{
  "pipeline_type": "dubbing",
  "input_uri": "https://example.com/video.mp4",
  "payload": {
    "target_language": "vi",
    "source_language": "en",
    "tts_voice": "vi-VN-HoaiMyNeural",
    "tts_engine": "edge-tts",
    "output_name": "video-quang-cao-mua-he"
  }
}
```

### `subtitle` — Chỉ tạo phụ đề
```json
{
  "pipeline_type": "subtitle",
  "input_uri": "https://example.com/video.mp4",
  "payload": {
    "target_language": "vi",
    "burn_subtitle": true,
    "output_name": "video-co-phu-de"
  }
}
```

### `audio_extract` — Trích xuất âm thanh
```json
{
  "pipeline_type": "audio_extract",
  "input_uri": "https://example.com/video.mp4",
  "payload": {
    "normalize_loudness": true,
    "output_name": "podcast-episode-1"
  }
}
```

### `multilang_dubbing` — Dịch nhiều thứ tiếng cùng lúc
```json
{
  "pipeline_type": "multilang_dubbing",
  "input_uri": "https://example.com/video.mp4",
  "payload": {
    "target_languages": ["vi", "ja", "ko", "en", "zh"],
    "source_language": "en"
  }
}
```

### `workflow` — Workflow DAG khai báo bằng JSON
```json
{
  "pipeline_type": "workflow",
  "input_uri": "https://example.com/video.mp4",
  "payload": {
    "workflow": {
      "nodes": {
        "extract": { "type": "media.extract_audio" },
        "transcribe": { "type": "ai.transcribe", "depends_on": ["extract"] }
      }
    }
  }
}
```

### `semantic_edit` — Biên tập theo intent
```json
{
  "pipeline_type": "semantic_edit",
  "input_uri": "https://example.com/video.mp4",
  "payload": {
    "command": "make_tiktok_short",
    "target_duration": 60
  }
}
```

---

## 6. 🔧 Payload Parameters Toàn Tập

Các key phổ biến có thể thêm vào trường `payload` của bất kỳ Job nào:

| Key | Kiểu | Mô tả |
|---|---|---|
| `target_language` | `string` | Ngôn ngữ đích, ví dụ: `vi`, `en`, `ja`, `ko` |
| `source_language` | `string` | Ngôn ngữ gốc (`auto` để tự nhận dạng) |
| `tts_voice` | `string` | Tên giọng đọc AI (xem danh sách theo engine) |
| `tts_engine` | `string` | `edge-tts` / `openai` / `google-cloud` |
| `tts_rate` | `string` | Tốc độ giọng đọc, ví dụ: `+10%`, `-20%` |
| `tts_volume` | `string` | Âm lượng giọng đọc, ví dụ: `+5%` |
| `tts_parallel_workers` | `int` | Số luồng tổng hợp giọng nói song song (default: 1) |
| `burn_subtitle` | `bool` | Đóng cứng phụ đề lên video (default: `false`) |
| `output_name` | `string` | **Tên thư mục output tùy chỉnh** thay vì UUID |
| `cache_bust` | `bool` | `true` để bỏ qua cache, render lại từ đầu |
| `priority` | `int` | Độ ưu tiên trong hàng đợi (số cao = ưu tiên cao) |

---

## 7. 📊 Theo Dõi & Monitoring

```bash
# Xem metrics Prometheus
curl http://localhost:6666/metrics

# Xem trạng thái job realtime qua SSE
curl -N http://localhost:6666/jobs/{job_id}/stream \
  -H "X-API-Key: your-key"
```

### Tích hợp Grafana:
Trỏ Prometheus scrape tới `http://<server>:6666/metrics`, sau đó import dashboard Grafana để theo dõi `active_jobs`, `job_submitted_total`, và `job_completed_total`.

---

## 8. 🧪 Chạy Tests

```bash
# Chạy toàn bộ bộ test (66 tests)
python -m pytest

# Chạy kèm báo cáo coverage
python -m pytest --cov=. --cov-report=html
```
