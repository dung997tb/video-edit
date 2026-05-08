# 📋 PLANS.MD — Kế Hoạch Phát Triển v3.0
## AI Video Automation Engine — Roadmap Kỹ Thuật Có Thể Implement Ngay

> Cập nhật: 2026-05-08 | v2.0 → v3.0
> **Hiện có:** 20 operations trong `VIDEO_OPERATION_MODULES` (đã đếm chính xác từ `low_level.py`)
> **Mục tiêu v3.0:** 37 operations + 3 AI pipelines mới = **40 tính năng tổng**

---

## ⚠️ Vấn Đề Cần Sửa Trước Khi Implement

### 1. Chuẩn hóa tên pipeline (Pipeline Naming)
**Hiện trạng không nhất quán:**
```python
"multilang-dubbing"   # dùng dash (NAME trong orchestrator)
"audio-extract"       # dùng dash (NAME gốc)
"audio_extract"       # dùng underscore (alias trong factory.py)
```
**Quy tắc chuẩn từ đây:** Tất cả pipeline mới dùng **underscore** (`snake_case`).
- Việc cần làm: Thêm alias `"multilang_dubbing"` → `result["multilang-dubbing"]` vào `factory.py`

### 2. Operation Output Contract
Mỗi operation phải khai báo rõ kiểu output của nó:

| Contract Type | Ý nghĩa | Ví dụ |
|---|---|---|
| `working_video` | Trả về 1 file video, chain tiếp được | `cut`, `flip`, `scale` |
| `output_files` | Trả về nhiều file, KHÔNG chain tiếp | `split_equal`, `extract_frame` |
| `guard_only` | Không đổi file, chỉ validate | `filter_duration` |
| `working_audio` | Trả về 1 file audio | `audio_pitch` |

**Quy tắc:** Operation kiểu `output_files` **không được** nằm trong chuỗi `operations[]` bình thường — phải là pipeline riêng hoặc là operation cuối cùng trong chuỗi.

---

## 🔧 PHASE 0 — Chuẩn Hóa (Làm Trước Hết)
**Thời gian:** 1–2 ngày | **Không tạo tính năng mới, chỉ dọn dẹp**

### Việc cần làm:
- [ ] **`orchestrators/factory.py`**: Thêm alias `multilang_dubbing` → `multilang-dubbing`
- [ ] **`modules/video/low_level.py`**: Thêm comment phân loại contract type cho từng entry hiện có
- [ ] **`requirements.txt`**: Tách dependency nặng ra file riêng `requirements-ai.txt`

```
# requirements.txt (giữ nhẹ — chạy được không cần GPU)
# ... giữ nguyên các dep hiện tại ...

# requirements-ai.txt (cài khi cần AI features)
silero-vad>=4.0
torch>=2.0.0
torchaudio>=2.0.0
ass>=0.5.0
mediapipe>=0.10.0
opencv-python>=4.8.0
```

---

## ⚡ PHASE 1A — Operations An Toàn (Single-input/output)
**Thời gian:** 3–5 ngày | **Dễ nhất, không rủi ro**
**Contract:** Tất cả trả về `working_video` hoặc `guard_only`

### Danh sách file cần tạo:

| Operation | File | Contract | FFmpeg chính |
|---|---|---|---|
| `pad_border` | `modules/video/pad_border.py` | working_video | `pad=iw+{s*2}:ih+{s*2}:{s}:{s}:{color}` |
| `blur_bg_portrait` | `modules/video/blur_bg_portrait.py` | working_video | `scale→boxblur→overlay` |
| `loop` | `modules/video/loop.py` | working_video | concat demuxer (tránh `-c copy` lỗi timestamp) |
| `filter_duration` | `modules/video/filter_duration.py` | guard_only | ffprobe → validate, không đổi file |
| `delogo` | `modules/video/delogo.py` | working_video | `delogo` hoặc `boxblur` vùng chỉ định |
| `audio_pitch` | `modules/audio/audio_pitch.py` | working_video | `asetrate*2^(n/12),aresample` + xử lý atempo chain |
| `content_variant` | `modules/video/content_variant.py` | working_video | `noise+hue+setpts` kết hợp (đổi tên từ `anti_reup`) |

**Chi tiết kỹ thuật quan trọng:**

**`loop.py`** — Không dùng `-stream_loop -c copy` vì lỗi timestamp với nhiều codec. Thay bằng:
```python
# Tạo file list rồi dùng concat demuxer:
# file 'input.mp4'
# file 'input.mp4'   (lặp lại N lần)
ffmpeg -f concat -safe 0 -i filelist.txt -c:v libx264 -c:a aac output.mp4
```

**`audio_pitch.py`** — FFmpeg `atempo` chỉ nhận range `[0.5, 100.0]`. Nếu factor ngoài range phải chain nhiều atempo:
```python
# factor = 2^(semitones/12)
# Nếu factor > 2.0: dùng atempo=2.0,atempo={factor/2}
# Nếu factor < 0.5: dùng atempo=0.5,atempo={factor*2}
```

**`blur_bg_portrait.py`** — FFmpeg filter đầy đủ:
```
-filter_complex
  "[0:v]scale=W:H:force_original_aspect_ratio=increase,
   crop=W:H,
   boxblur={sigma}:5[bg];
   [0:v]scale=iw*min(W/iw\,H/ih):ih*min(W/iw\,H/ih)[fg];
   [bg][fg]overlay=(W-w)/2:(H-h)/2[out]"
```

### Cập nhật `low_level.py` sau Phase 1A:
```python
# Thêm 7 entries mới:
"pad_border":        PadBorderModule,        # working_video
"blur_bg_portrait":  BlurBgPortraitModule,   # working_video
"loop":              LoopModule,             # working_video
"filter_duration":   FilterDurationModule,   # guard_only
"delogo":            DelogoModule,           # working_video
"audio_pitch":       AudioPitchModule,       # working_video
"content_variant":   ContentVariantModule,   # working_video
```

---

## ⚡ PHASE 1B — Operations Multi-input / Multi-output
**Thời gian:** 5–7 ngày | **Phức tạp hơn, cần xử lý edge cases**

### Quy tắc bắt buộc cho nhóm này:
Trước khi ghép 2+ video, **PHẢI normalize** về cùng `resolution + FPS + pixel_format + sample_rate`.
Dùng helper function chung: `normalize_video_for_compose(path, target_w, target_h, fps=30)`.

| Operation | File | Contract | Lưu ý kỹ thuật |
|---|---|---|---|
| `hstack` | `modules/video/hstack.py` | working_video | Scale cả 2 về cùng height trước; xử lý audio missing bằng `aevalsrc=0` |
| `split_screen` | `modules/video/split_screen.py` | working_video | vstack sau khi scale; audio từ source chính |
| `chromakey` | `modules/video/chromakey.py` | working_video | Cần `-pix_fmt yuva420p` hoặc explicit pixel format |
| `grid` | `modules/video/grid.py` | working_video | Xây dynamic `filter_complex` theo số lượng video |
| `convert` | `modules/video/convert.py` | working_video | Codec map rõ ràng; audio-only khi format là mp3/aac/wav |
| `random_mirror` | `modules/video/random_mirror.py` | working_video | trim+hflip+concat; phải re-encode để tránh lỗi timestamp |

**Chi tiết kỹ thuật quan trọng:**

**`hstack.py`** — Xử lý video thiếu audio track:
```python
# Kiểm tra audio stream trước bằng ffprobe
# Nếu thiếu: thêm -f lavfi -i aevalsrc=0:c=stereo:r=44100:d={duration}
# Dùng amerge thay vì amix để đồng bộ channel
```

**`chromakey.py`** — Pixel format bắt buộc:
```
-filter_complex
  "[1:v]format=yuva420p,colorkey=color={hex}:similarity={s}:blend={b}[fg];
   [0:v][fg]overlay[out]"
```

**`grid.py`** — Xây dynamic filter:
```python
# videos = [v0, v1, v2, v3], cols=2, rows=2
# cell_w = output_w // cols, cell_h = output_h // rows
# Scale: [N:v]scale=cell_w:cell_h[sN]
# Xếp từng hàng: [s0][s1]hstack[row0], [s2][s3]hstack[row1]
# Ghép hàng: [row0][row1]vstack[out]
```

### Operations thuộc pipeline riêng (KHÔNG vào `low_level`):

| Operation | Pipeline Name | File | Lý do |
|---|---|---|---|
| `split_equal` | `split_video` | `orchestrators/split_video_orchestrator.py` | Output nhiều file |
| `extract_frame` | `extract_frames` | `orchestrators/extract_frames_orchestrator.py` | Output nhiều ảnh |

---

## 🔥 PHASE 2 — AI Retention Booster
**Thời gian:** 2–3 tuần | **Cần `requirements-ai.txt`**

### 2.1 Silence Cut (Làm trước)
- **Pipeline:** `silence_cut`
- **Files:** `modules/ai/silence_remover.py` + `orchestrators/silence_cut_orchestrator.py`
- **Deps:** `silero-vad`, `torch`, `torchaudio`
- **Luồng:** extract WAV → silero-vad → speech segments → FFmpeg trim+concat
- **Schema output:** Giữ nguyên `working_video` contract

### 2.2 Karaoke Subtitle (Làm sau — cần thay đổi transcript schema)
- **Pipeline:** Mở rộng `subtitle` với `subtitle_style: "karaoke"`
- **Files:** `modules/ai/karaoke_subtitle.py` + sửa `subtitle_orchestrator.py`
- **Deps:** `ass` library + Whisper `word_timestamps=True`
- **Lưu ý:** Whisper word-timestamps đổi schema transcript → phải versioning cẩn thận
- **Deps:** `ass>=0.5.0`

### 2.3 Auto Zoom
- **Operation:** `auto_zoom` → vào `low_level` (contract: `working_video`)
- **File:** `modules/video/auto_zoom.py`
- **Không cần AI dep**, chỉ FFmpeg `zoompan` filter

### 2.4 Split Screen
- **Đã được kế hoạch ở Phase 1B** (`split_screen.py`)

---

## 🎨 PHASE 3 — Content Variant Tools
*(Đổi tên từ "Anti-Reup" — hướng hợp pháp: tạo biến thể nội dung cho đa nền tảng)*

**Thời gian:** 3–5 ngày | **Chỉ FFmpeg, không dep nặng**

| Operation | File | Mục đích hợp pháp |
|---|---|---|
| `content_variant` | `modules/video/content_variant.py` | Tạo biến thể kỹ thuật: tốc độ nhẹ, tiếng ồn hạt phim, màu sắc |
| `audio_pitch` | `modules/audio/audio_pitch.py` | Đổi cao độ âm thanh (localization, accessibility) |
| `random_mirror` | `modules/video/random_mirror.py` | Tạo phiên bản mirror cho thị trường RTL (Arabic/Hebrew) |

**`content_variant.py`** — Các điều chỉnh hợp pháp:
```
-vf "setpts=PTS/{speed},
     noise=c0s={grain}:c0f=t+u,
     hue=h={hue_shift}:s={sat}"
-af "asetrate=44100*{pitch},aresample=44100,atempo={1/speed}"
```
Mục đích: Format chuẩn hóa cho nền tảng khác nhau (TikTok 9:16, YouTube 16:9, IG Square).

---

## 🤖 PHASE 4 — AI Nâng Cao (Spike Trước, Code Sau)
**Cần nghiên cứu trước khi code — tránh over-engineering**

### 4.1 Face Tracking Portrait
- **Spike cần làm:** Đo thời gian xử lý 1 phút video trên CPU (mediapipe)
- **Nếu > 5× realtime:** Cần GPU hoặc chiến lược sampling thưa hơn
- **Files:** `modules/ai/face_tracker.py` + `orchestrators/face_track_orchestrator.py`
- **Pipeline:** `face_track_portrait`

### 4.2 Auto B-Roll Injection
- **Phụ thuộc:** Transcript schema từ Phase 2.2 (karaoke subtitle)
- **Files:** `modules/ai/broll_injector.py` + `orchestrators/auto_broll_orchestrator.py`
- **Pipeline:** `auto_broll`
- **Làm sau cùng** vì phụ thuộc nhiều module khác đã phải xong

---

## 📊 Số Liệu Chính Xác

| | Hiện tại (v2.0) | Sau v3.0 |
|---|---|---|
| Low-level operations | **20** | **34** |
| AI Pipelines | 5 | 8 |
| Tổng tính năng API | **25** | **42** |

---

## ✅ Checklist Theo Thứ Tự Thực Hiện

**Phase 0 (Dọn dẹp):**
- [ ] Thêm alias `multilang_dubbing` trong `factory.py`
- [ ] Tạo `requirements-ai.txt`

**Phase 1A (7 operations đơn giản):**
- [ ] `pad_border.py`
- [ ] `blur_bg_portrait.py`
- [ ] `loop.py` (concat demuxer, không `-c copy`)
- [ ] `filter_duration.py`
- [ ] `delogo.py`
- [ ] `audio_pitch.py` (xử lý atempo chain)
- [ ] `content_variant.py`
- [ ] Cập nhật `low_level.py` (+7 entries)

**Phase 1B (6 operations phức tạp):**
- [ ] `hstack.py` (xử lý audio missing)
- [ ] `split_screen.py`
- [ ] `chromakey.py` (pixel format)
- [ ] `grid.py` (dynamic filter_complex)
- [ ] `convert.py`
- [ ] `random_mirror.py`
- [ ] `split_video_orchestrator.py` (pipeline riêng)
- [ ] `extract_frames_orchestrator.py` (pipeline riêng)
- [ ] Cập nhật `low_level.py` (+4 entries)

**Phase 2 (AI Retention):**
- [ ] `silence_remover.py` + orchestrator
- [ ] `auto_zoom.py`
- [ ] `karaoke_subtitle.py` + sửa `subtitle_orchestrator.py`

**Phase 4 (AI Nâng Cao — sau spike):**
- [ ] Spike face tracking performance
- [ ] `face_tracker.py` + orchestrator
- [ ] `broll_injector.py` + orchestrator

---

*Tổng: ~22 files mới + 3 files sửa = **Đủ để nâng lên v3.0***
