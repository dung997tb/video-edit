# 📋 PLANS.MD — Kế Hoạch Phát Triển Tiếp Theo
## AI Video Automation Engine — Lộ Trình Nâng Cấp Lên Bộ Công Cụ 52 Tính Năng

> Cập nhật lần cuối: 2026-05-08
> Trạng thái hiện tại: **v2.0 Production-Ready** — 22 operations đang có.
> Mục tiêu: **v3.0** — 52 operations + AI Retention + Anti-Reup Engine.

---

## 🗂️ Tổng Quan Roadmap

| Phase | Tên | Số File Mới | Ưu Tiên | Thời Gian |
|---|---|---|---|---|
| **Phase 1** | 15 Low-level Operations Còn Thiếu | 15 file mới, 1 sửa | 🔴 Cao nhất | 1–2 tuần |
| **Phase 2** | 4 Retention Booster (Giữ chân người xem) | 5 file mới, 1 sửa | 🟠 Cao | 2–3 tuần |
| **Phase 3** | 3 Anti-Reup / Unique (Lách bản quyền) | 2 file mới | 🟠 Cao | 3–5 ngày |
| **Phase 4** | 2 AI Nâng Cao (Face Tracking, B-Roll) | 5 file mới, 1 sửa | 🟡 Trung bình | 4–6 tuần |

---

## ⚡ PHASE 1 — 15 Low-Level Operations Còn Thiếu

> **Chiến lược:** Mỗi operation = 1 file Python mới, theo đúng pattern `modules/video/cut.py`.
> Sau khi tạo xong, đăng ký vào `VIDEO_OPERATION_MODULES` dict trong `modules/video/low_level.py`.

### ✅ Operations Hiện Có (22 operations)
`cut`, `speed`, `flip`, `crop`, `rotate`, `scale`, `concat`, `overlay`, `watermark`, `denoise`, `color_grade`,
`audio_trim`, `audio_speed`, `audio_volume`, `audio_fade`, `audio_normalize`,
`visual_blur`, `visual_sharpen`, `visual_grayscale`, `visual_vignette`

### 🔲 1.1 — `split_equal` | Chia video thành N phần bằng nhau
- **File:** `modules/video/split_equal.py`
- **FFmpeg:** `-f segment -segment_time {seg_duration} -reset_timestamps 1 output_%03d.mp4`
- **Params:** `parts` (int), `output_prefix` (str, optional)
- **Logic:** ffprobe → duration ÷ parts = segment_duration → chạy segment muxer
- **Output:** Danh sách path: `[part_001.mp4, part_002.mp4, ...]`
- **Phủ mục:** 1, 4 trong danh sách 38

### 🔲 1.2 — `extract_frame` | Chụp ảnh từ video
- **File:** `modules/video/extract_frame.py`
- **FFmpeg (theo interval):** `ffmpeg -i input.mp4 -vf fps=1/{interval} frame_%04d.jpg`
- **FFmpeg (theo timestamp):** `ffmpeg -i input.mp4 -ss {t} -frames:v 1 frame_{t}.jpg`
- **Params:** `timestamps` (list[float] | None), `interval` (float | None), `format` ("jpg"|"png")
- **Phủ mục:** 36

### 🔲 1.3 — `hstack` | Video Duet / Side-by-Side
- **File:** `modules/video/hstack.py`
- **FFmpeg:**
  ```
  -filter_complex "[0:v]scale=iw:ih[v0];[1:v]scale=iw:ih[v1];[v0][v1]hstack=inputs=2[v];[0:a][1:a]amerge=inputs=2[a]"
  -map "[v]" -map "[a]"
  ```
- **Params:** `second_video` (str, required), `layout` ("horizontal"|"vertical")
- **Phủ mục:** 28 (Tạo video Duet)

### 🔲 1.4 — `chromakey` | Chèn video phông xanh
- **File:** `modules/video/chromakey.py`
- **FFmpeg:**
  ```
  -filter_complex "[1:v]colorkey=color=0x00FF00:similarity=0.3:blend=0.1[fg];[0:v][fg]overlay[out]"
  ```
- **Params:** `background_video` (str), `color` ("#00FF00"), `similarity` (0.3), `blend` (0.1)
- **Phủ mục:** 32

### 🔲 1.5 — `grid` | Lưới nhiều video (Grid Layout)
- **File:** `modules/video/grid.py`
- **FFmpeg:** Tạo động `filter_complex` string theo số lượng video
- **Params:** `videos` (list[str], required), `cols` (int), `rows` (int), `output_width` (1080), `output_height` (1920)
- **Logic:** Scale mỗi video → kích thước ô = target/cols×rows → overlay từng ô
- **Phủ mục:** 13

### 🔲 1.6 — `delogo` | Xóa logo / phụ đề
- **File:** `modules/video/delogo.py`
- **FFmpeg (mode=delogo):** `-vf "delogo=x={x}:y={y}:w={w}:h={h}"`
- **FFmpeg (mode=blur):** `-vf "split[m][b];[b]crop={w}:{h}:{x}:{y},boxblur=10:5[blr];[m][blr]overlay={x}:{y}"`
- **Params:** `x`, `y`, `w`, `h` (int, required), `mode` ("delogo"|"blur")
- **Phủ mục:** 35

### 🔲 1.7 — `pad_border` | Thêm viền màu
- **File:** `modules/video/pad_border.py`
- **FFmpeg:** `-vf "pad=iw+{size*2}:ih+{size*2}:{size}:{size}:color={color}"`
- **Params:** `size` (int, default=20), `color` (str, default="black")
- **Phủ mục:** 16

### 🔲 1.8 — `blur_bg_portrait` | Nền mờ dọc 9:16
- **File:** `modules/video/blur_bg_portrait.py`
- **FFmpeg:**
  ```
  -filter_complex
    "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[bg];
     [0:v]scale=1080:-2[fg];
     [bg][fg]overlay=(W-w)/2:(H-h)/2[out]"
  ```
- **Params:** `output_width` (1080), `output_height` (1920), `blur_sigma` (25)
- **Phủ mục:** 10, 31

### 🔲 1.9 — `loop` | Lặp lại video N lần
- **File:** `modules/video/loop.py`
- **FFmpeg:** `ffmpeg -stream_loop {times-1} -i input.mp4 -c copy output.mp4`
- **Params:** `times` (int, default=2)
- **Phủ mục:** 19

### 🔲 1.10 — `convert` | Chuyển đổi định dạng
- **File:** `modules/video/convert.py`
- **Codec Map:**
  ```
  mp4  → libx264 + aac
  webm → libvpx-vp9 + libopus
  avi  → mpeg4 + mp3
  mp3  → -vn + libmp3lame  (audio only)
  aac  → -vn + aac         (audio only)
  wav  → -vn + pcm_s16le   (audio only)
  ```
- **Params:** `output_format` ("mp4"|"webm"|"avi"|"mp3"|"aac"|"wav")
- **Phủ mục:** 8, 29

### 🔲 1.11 — `filter_duration` | Lọc video theo độ dài
- **File:** `modules/video/filter_duration.py`
- **Logic:** ffprobe duration → so sánh với min/max → raise nếu không đủ điều kiện
- **Params:** `min_seconds` (float|None), `max_seconds` (float|None)
- **Đây là "guard operation":** Không xử lý video, chỉ validate. Context.current_file không đổi.
- **Phủ mục:** 33

### 🔲 1.12 — `audio_pitch` | Đổi cao độ âm thanh
- **File:** `modules/audio/audio_pitch.py`
- **FFmpeg:** `-af "asetrate=44100*{factor},aresample=44100"`
  - `factor = 2^(semitones/12)`
  - Nếu `preserve_tempo=True`: thêm `atempo={1/factor}` để bù tốc độ
- **Params:** `semitones` (float, default=1.0), `preserve_tempo` (bool, default=True)
- **Phủ mục:** Anti-Reup Phase 3

### 🔲 1.13 — `auto_zoom` | Hiệu ứng giật zoom
- **File:** `modules/video/auto_zoom.py`
- **FFmpeg (mode=interval):**
  ```
  -vf "zoompan=z='if(lte(mod(on,{fps*interval}),{fps*trans}),zoom+0.005,
       if(lte(mod(on,{fps*interval}),{fps*trans}*2),zoom-0.005,zoom))':
       d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}"
  ```
- **Params:** `mode` ("interval"|"audio"), `interval_seconds` (4), `zoom_factor` (1.1), `transition_duration` (0.3)
- **Phủ mục:** Retention Booster

### 🔲 1.14 — `split_screen` | Chia đôi màn hình dọc
- **File:** `modules/video/split_screen.py`
- **FFmpeg:**
  ```
  -i main.mp4 -i broll.mp4
  -filter_complex "[0:v]scale=1080:960[top];[1:v]scale=1080:960[bot];[top][bot]vstack[v]"
  -map "[v]" -map 0:a
  ```
- **Params:** `b_roll_video` (str, required), `split_ratio` (0.5), `audio_source` ("main"|"b_roll"|"mix")
- **Phủ mục:** Retention Booster

### 🔲 1.15 — `random_mirror` | Lật ngẫu nhiên theo đoạn (Anti-Reup)
- **File:** `modules/video/random_mirror.py`
- **Logic:**
  1. ffprobe → duration → chia segments
  2. Mỗi segment: `random() < flip_probability` → thêm `hflip`
  3. Xây `filter_complex`: `[0:v]trim={s}:{e},setpts=PTS-STARTPTS[,hflip][seg{i}]`
  4. `concat` tất cả segments
- **Params:** `flip_probability` (0.4), `segment_duration` (3.0)
- **Phủ mục:** Anti-Reup

### 📝 Sửa file hiện có: `modules/video/low_level.py`
Thêm 15 import mới + 15 entries vào `VIDEO_OPERATION_MODULES`:
```python
from modules.video.split_equal import SplitEqualModule
from modules.video.extract_frame import ExtractFrameModule
from modules.video.hstack import HstackModule
from modules.video.chromakey import ChromakeyModule
from modules.video.grid import GridModule
from modules.video.delogo import DelogoModule
from modules.video.pad_border import PadBorderModule
from modules.video.blur_bg_portrait import BlurBgPortraitModule
from modules.video.loop import LoopModule
from modules.video.convert import ConvertModule
from modules.video.filter_duration import FilterDurationModule
from modules.video.auto_zoom import AutoZoomModule
from modules.video.split_screen import SplitScreenModule
from modules.video.random_mirror import RandomMirrorModule
from modules.audio.audio_pitch import AudioPitchModule
```

---

## 🔥 PHASE 2 — 4 Retention Booster

### 🔲 2.1 — Silence Remover | Auto Jump-Cut ⭐ ƯU TIÊN
- **File mới:** `modules/ai/silence_remover.py`
- **Orchestrator mới:** `orchestrators/silence_cut_orchestrator.py`
- **Pipeline name:** `silence_cut`
- **Dependencies:** `pip install silero-vad torch torchaudio`
- **Luồng xử lý:**
  1. `ffmpeg -vn -ar 16000` → extract audio sang WAV
  2. `silero-vad` → phân tích → list `[(start, end)]` các đoạn có tiếng nói
  3. Thêm `padding_ms` (100ms) trước/sau mỗi segment tránh cắt cứng
  4. Xây `filter_complex` tuần tự: `[0:v]trim={s}:{e},setpts=PTS-STARTPTS[v{i}]`
  5. `concat` tất cả → xuất file không có khoảng lặng
- **Payload mẫu:**
  ```json
  {
    "pipeline_type": "silence_cut",
    "payload": { "threshold_db": -40, "min_silence_duration": 0.5, "padding_ms": 100 }
  }
  ```

### 🔲 2.2 — Karaoke Subtitle | Phụ đề động Hormozi
- **File mới:** `modules/ai/karaoke_subtitle.py`
- **Sửa:** `orchestrators/subtitle_orchestrator.py` — thêm nhánh `style == "karaoke"`
- **Dependencies:** `pip install ass`
- **Luồng xử lý:**
  1. Whisper `word_timestamps=True` → timestamps từng chữ
  2. Xây file `.ass` với tag `\k{duration}` cho mỗi word
  3. Style active: **VÀNG** `#FFFF00`, bold, shadow — inactive: trắng 70% opacity
  4. Emoji injection qua keyword dict (built-in ~50 từ VN+EN)
  5. `ffmpeg -vf "subtitles=karaoke.ass:fontsdir=fonts/"` → burn vào video
- **Payload mẫu:**
  ```json
  {
    "pipeline_type": "dubbing",
    "payload": { "subtitle_style": "karaoke", "active_color": "#FFFF00", "font_size": 72, "add_emoji": true }
  }
  ```

### 🔲 2.3 — Auto Zoom | Giật zoom theo nhịp
- **File mới:** `modules/video/auto_zoom.py` ← đã mô tả ở Phase 1 (1.13)
- **Đăng ký:** thêm `"auto_zoom": AutoZoomModule` vào `low_level.py`

### 🔲 2.4 — Split Screen | Màn hình đôi 9:16
- **File mới:** `modules/video/split_screen.py` ← đã mô tả ở Phase 1 (1.14)
- **Đăng ký:** thêm `"split_screen": SplitScreenModule` vào `low_level.py`

---

## 🛡️ PHASE 3 — 3 Anti-Reup / Unique

> Tất cả FFmpeg filter thuần. Có thể xong trong **1-2 ngày**.

### 🔲 3.1 — `random_mirror` | Lật ngẫu nhiên
- Đã mô tả đầy đủ ở Phase 1 (1.15)

### 🔲 3.2 — `anti_reup` | Phá vỡ Video Fingerprint
- **File mới:** `modules/video/anti_reup.py`
- **FFmpeg (1 lệnh duy nhất):**
  ```
  -vf "setpts=PTS/{speed_factor},
       rotate={deg}*PI/180:ow=iw:oh=ih:c=black,
       noise=c0s={noise}:c0f=t+u,
       hue=h={hue}:s={sat}"
  -af "asetrate=44100*{pitch_factor},aresample=44100,atempo={1/speed_factor}"
  ```
- **Params (defaults):**
  - `speed_factor`: 1.02 (gần như không ai nhận ra)
  - `rotation_degree`: 0.5° (vô hình)
  - `noise_strength`: 3 (hạt phim siêu nhỏ)
  - `color_shift`: 2 (hue dịch 2°)
  - `audio_pitch_semitones`: 0.5

### 🔲 3.3 — `audio_pitch` | Đổi tần số âm thanh
- Đã mô tả đầy đủ ở Phase 1 (1.12)

---

## 🤖 PHASE 4 — 2 AI Nâng Cao

> ⚠️ Cần thêm `mediapipe`, `opencv-python`. Khuyến nghị GPU. Thời gian lâu hơn.

### 🔲 4.1 — Face Tracking | Bám theo khuôn mặt
- **File mới:** `modules/ai/face_tracker.py`
- **Orchestrator mới:** `orchestrators/face_track_orchestrator.py`
- **Pipeline name:** `face_track_portrait`
- **Dependencies:** `pip install mediapipe opencv-python`
- **Luồng xử lý:**
  1. OpenCV đọc video, lấy 1 frame/giây
  2. MediaPipe FaceDetection → `(cx, cy)` trung tâm khuôn mặt
  3. Smoothing: moving average window 30 frames → tránh giật
  4. Tạo list `[(timestamp, cx, cy)]` → serialize thành FFmpeg `crop` expression
  5. Scale output → 1080×1920
- **Fallback:** Nếu không phát hiện khuôn mặt → crop center mặc định

### 🔲 4.2 — Auto B-Roll | Chèn B-Roll tự động theo từ khóa
- **File mới:** `modules/ai/broll_injector.py`
- **Orchestrator mới:** `orchestrators/auto_broll_orchestrator.py`
- **Pipeline name:** `auto_broll`
- **Luồng xử lý:**
  1. Chạy `transcriber` (Whisper, đã có) → transcript + timestamps
  2. Đọc `keyword_map` từ payload
  3. Quét transcript → tìm keyword → lấy timestamp `(start, end)`
  4. Tại mỗi match: trim B-roll clip → overlay lên main video với fade 0.3s
  5. Conflict resolution: keyword đầu tiên được ưu tiên

---

## 📁 Danh Sách Đầy Đủ Files Cần Tạo

### Files MỚI (25 files)
```
modules/video/
  ├── split_equal.py
  ├── extract_frame.py
  ├── hstack.py
  ├── chromakey.py
  ├── grid.py
  ├── delogo.py
  ├── pad_border.py
  ├── blur_bg_portrait.py
  ├── loop.py
  ├── convert.py
  ├── filter_duration.py
  ├── auto_zoom.py
  ├── split_screen.py
  ├── random_mirror.py
  └── anti_reup.py
modules/audio/
  └── audio_pitch.py
modules/ai/
  ├── silence_remover.py
  ├── karaoke_subtitle.py
  ├── face_tracker.py
  └── broll_injector.py
orchestrators/
  ├── silence_cut_orchestrator.py
  ├── face_track_orchestrator.py
  └── auto_broll_orchestrator.py
pipelines/examples/
  ├── silence_cut.json
  ├── face_track_portrait.json
  └── auto_broll.json
```

### Files HIỆN TẠI cần sửa (3 files)
```
modules/video/low_level.py            → +15 import + 15 dict entries
orchestrators/factory.py              → +3 orchestrator registrations
orchestrators/subtitle_orchestrator.py → +karaoke style branch
```

---

## 📦 Cập Nhật `requirements.txt`

```
# Phase 2 — Silence Removal + Karaoke
silero-vad>=4.0
torch>=2.0.0
torchaudio>=2.0.0
ass>=0.5.0

# Phase 4 — Face Tracking
mediapipe>=0.10.0
opencv-python>=4.8.0
```

---

## 🧪 Kế Hoạch Kiểm Thử Sau Mỗi Phase

```bash
# Sau Phase 1+3 (FFmpeg operations):
python -m pytest tests/ -v -k "test_low_level"

# Test riêng từng operation:
python main.py run ./test.mp4 --config-file ./pipelines/examples/low_level_basic.json

# Sau Phase 2 (Silence Cut):
python main.py run ./test.mp4 --config-file ./pipelines/examples/silence_cut.json

# Full regression test:
python -m pytest
```

---

## ✅ Checklist Trạng Thái

### Phase 1
- [ ] `split_equal.py`
- [ ] `extract_frame.py`
- [ ] `hstack.py`
- [ ] `chromakey.py`
- [ ] `grid.py`
- [ ] `delogo.py`
- [ ] `pad_border.py`
- [ ] `blur_bg_portrait.py`
- [ ] `loop.py`
- [ ] `convert.py`
- [ ] `filter_duration.py`
- [ ] `audio_pitch.py`
- [ ] `auto_zoom.py`
- [ ] `split_screen.py`
- [ ] `random_mirror.py`
- [ ] Cập nhật `low_level.py` (thêm 15 entries)

### Phase 2
- [ ] `silence_remover.py` + `silence_cut_orchestrator.py`
- [ ] `karaoke_subtitle.py` + sửa `subtitle_orchestrator.py`

### Phase 3
- [ ] `anti_reup.py`
- [ ] Cập nhật `factory.py`

### Phase 4
- [ ] `face_tracker.py` + `face_track_orchestrator.py`
- [ ] `broll_injector.py` + `auto_broll_orchestrator.py`

---

*Khi hoàn thành toàn bộ 4 Phase, hệ thống sẽ đạt: **52 tính năng — Phiên bản v3.0***
