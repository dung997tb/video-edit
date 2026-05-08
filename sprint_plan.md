# 🎯 SPRINT PLAN — Hoàn Thiện & Test Thực Tế
## Mục tiêu: Hoàn thành nốt plans.md + Test mọi tính năng trên video thực

> Ngày bắt đầu: 2026-05-08
> Trạng thái: **77/77 tests pass** — Sẵn sàng mở rộng
> Ưu tiên: Nối dây → Code → Test video thực

---

## 🔴 SPRINT 1 — Nối Dây Các Tính Năng Đã Có (1–2 ngày)
*Code đã có, chỉ cần đăng ký và kết nối*

### Task 1.1 — Đăng ký `workflow` pipeline vào factory
**File sửa:** `orchestrators/factory.py`
```python
# Thêm WorkflowOrchestrator
result["workflow"] = WorkflowOrchestrator()
result["semantic_edit"] = SemanticEditOrchestrator()
```
**File tạo mới:** `orchestrators/workflow_orchestrator.py`
- Nhận `payload.workflow.nodes` → build `WorkflowSpec` → chạy qua `DAGRunner` đã có
- Dùng `core/workflow/compat.py` để bridge với step cache

**File tạo mới:** `orchestrators/semantic_edit_orchestrator.py`
- Nhận `payload.command` (vd: `make_tiktok_short`) → gọi `core/semantic/analyzers.py` → trả về timeline edits
- MVP: chỉ support `command: silence_cut` trước

### Task 1.2 — Chuẩn hóa alias pipeline name
**File sửa:** `orchestrators/factory.py`
```python
result["multilang_dubbing"] = result["multilang-dubbing"]  # thêm alias underscore
```

### Task 1.3 — Tạo file example JSON cho pipeline mới
**Files tạo mới trong `pipelines/examples/`:**
- `workflow_dag_example.json` — ví dụ DAG với 2 nodes
- `semantic_silence_cut.json` — ví dụ silence_cut qua semantic
- `content_variant.json` — ví dụ tạo biến thể nội dung

### Test Sprint 1:
```bash
python -m pytest tests/test_orchestrator_registration.py -v
python main.py run ./test.mp4 --config-file ./pipelines/examples/workflow_dag_example.json
```
- [ ] Task 1.1 — WorkflowOrchestrator
- [ ] Task 1.2 — SemanticEditOrchestrator
- [ ] Task 1.3 — Alias multilang_dubbing
- [ ] Task 1.4 — 3 file JSON examples

---

## 🟠 SPRINT 2 — Phase 1A: 7 Operations Đơn Giản (3–4 ngày)
*Tất cả single I/O, không cần Timeline Model*

### Task 2.1 — `pad_border` | Tạo viền màu cho video
**File:** `modules/video/pad_border.py`
```python
# FFmpeg: pad=iw+{size*2}:ih+{size*2}:{size}:{size}:color={color}
# Params: size (int, default=20), color (str, default="black")
# Contract: working_video
```
**Test thực tế:** Video 1280x720 + viền 30px trắng → output 1340x780

### Task 2.2 — `blur_bg_portrait` | Nền mờ dọc 9:16
**File:** `modules/video/blur_bg_portrait.py`
```python
# FFmpeg filter_complex:
#   [0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[bg]
#   [0:v]scale=iw*min(1080/iw\,1920/ih):ih*min(1080/iw\,1920/ih)[fg]
#   [bg][fg]overlay=(W-w)/2:(H-h)/2[out]
# Params: output_width=1080, output_height=1920, blur_sigma=25
# Contract: working_video
```
**Test thực tế:** Video ngang 16:9 → video dọc 9:16 có nền mờ

### Task 2.3 — `loop` | Lặp video N lần
**File:** `modules/video/loop.py`
```python
# KHÔNG dùng -stream_loop -c copy (lỗi timestamp!)
# Dùng concat demuxer:
#   Tạo file list: "file 'input.mp4'" × N lần
#   ffmpeg -f concat -safe 0 -i filelist.txt -c:v libx264 -c:a aac output.mp4
# Params: times (int, default=2)
# Contract: working_video
```
**Test thực tế:** Video 5s → lặp 3 lần → output 15s

### Task 2.4 — `filter_duration` | Guard: lọc theo độ dài
**File:** `modules/video/filter_duration.py`
```python
# ffprobe duration → validate min/max
# Contract: guard_only (không đổi file, chỉ raise nếu không đủ điều kiện)
# Params: min_seconds, max_seconds (cả 2 optional)
```
**Test thực tế:** Video 10s với `min_seconds=15` → phải raise lỗi rõ ràng

### Task 2.5 — `delogo` | Xóa logo / blur vùng
**File:** `modules/video/delogo.py`
```python
# mode=delogo: -vf "delogo=x={x}:y={y}:w={w}:h={h}"
# mode=blur:   -vf "split[m][b];[b]crop={w}:{h}:{x}:{y},boxblur=15:5[bl];[m][bl]overlay={x}:{y}"
# Params: x, y, w, h (required), mode ("delogo"|"blur", default="blur")
# Contract: working_video
```
**Test thực tế:** Blur góc trên trái 200x80px

### Task 2.6 — `audio_pitch` | Đổi cao độ âm thanh
**File:** `modules/audio/audio_pitch.py`
```python
# factor = 2^(semitones/12)
# Nếu preserve_tempo=True: thêm atempo={1/factor}
# QUAN TRỌNG: atempo chỉ nhận [0.5, 100.0]:
#   Nếu factor > 2.0: atempo=2.0,atempo={factor/2}
#   Nếu factor < 0.5: atempo=0.5,atempo={factor*2}
# Params: semitones=1.0, preserve_tempo=True
# Contract: working_video
```
**Test thực tế:** Tăng pitch 3 semitones, giọng nghe cao hơn nhưng tốc độ không đổi

### Task 2.7 — `content_variant` | Tạo biến thể nội dung
**File:** `modules/video/content_variant.py`
```python
# Một lệnh FFmpeg kết hợp nhiều micro-adjust hợp pháp:
# -vf "noise=c0s={grain}:c0f=t+u,hue=h={hue}:s={sat_factor}"
# -vf + setpts nếu speed_factor != 1.0
# -af "asetrate=44100*{pitch},aresample=44100" nếu audio_shift != 0
# Params:
#   speed_factor=1.0, grain=3, hue_shift=2.0, sat_factor=1.02, audio_shift_cents=0
# Contract: working_video
```
**Test thực tế:** Tạo biến thể video có hạt phim nhẹ + màu sắc dịch nhẹ

### Task 2.8 — Đăng ký vào `low_level.py`
```python
from modules.video.pad_border import PadBorderModule
from modules.video.blur_bg_portrait import BlurBgPortraitModule
from modules.video.loop import LoopModule
from modules.video.filter_duration import FilterDurationModule
from modules.video.delogo import DelogoModule
from modules.audio.audio_pitch import AudioPitchModule
from modules.video.content_variant import ContentVariantModule

VIDEO_OPERATION_MODULES.update({
    "pad_border": PadBorderModule,
    "blur_bg_portrait": BlurBgPortraitModule,
    "loop": LoopModule,
    "filter_duration": FilterDurationModule,
    "delogo": DelogoModule,
    "audio_pitch": AudioPitchModule,
    "content_variant": ContentVariantModule,
})
```

### Test Sprint 2 — Chạy Trên Video Thực:
```bash
# Tạo video test tổng hợp Phase 1A:
python main.py run ./test_input.mp4 --config-file ./pipelines/examples/phase1a_test.json

# phase1a_test.json sẽ chạy tuần tự:
# pad_border → blur_bg_portrait → audio_pitch → content_variant
```
- [ ] Task 2.1 — pad_border.py
- [ ] Task 2.2 — blur_bg_portrait.py
- [ ] Task 2.3 — loop.py (concat demuxer)
- [ ] Task 2.4 — filter_duration.py
- [ ] Task 2.5 — delogo.py
- [ ] Task 2.6 — audio_pitch.py (atempo chain)
- [ ] Task 2.7 — content_variant.py
- [ ] Task 2.8 — Cập nhật low_level.py

---

## 🟠 SPRINT 3 — Phase 1B: 6 Operations Multi-input (4–5 ngày)
*Cần xử lý edge cases: audio missing, resolution mismatch, pixel format*

### Helper chung cần tạo trước:
**File:** `modules/video/common.py` (mở rộng)
```python
def normalize_for_compose(path, target_w, target_h, fps=30, services=None):
    """Scale video về đúng resolution + fps trước khi ghép."""
    # ffmpeg -i input -vf "scale={w}:{h}:force_original_aspect_ratio=decrease,
    #   pad={w}:{h}:(ow-iw)/2:(oh-ih)/2" -r {fps} -c:v libx264 normalized.mp4

def ensure_audio_stream(path, duration, services=None):
    """Thêm audio track rỗng nếu video không có audio."""
    # ffprobe → check audio streams
    # Nếu thiếu: -f lavfi -i aevalsrc=0:c=stereo:r=44100:d={duration}
```

### Task 3.1 — `hstack` | Video Duet / Side-by-side
```python
# Trước: normalize 2 video về cùng height
# FFmpeg: [0:v][1:v]hstack=inputs=2[v];[0:a][1:a]amerge[a]
# Params: second_video (str), layout ("horizontal"|"vertical")
# Edge case: video thiếu audio → ensure_audio_stream
```
**Test thực tế:** 2 video khác nhau ghép ngang, âm thanh trộn đều

### Task 3.2 — `split_screen` | Màn hình đôi dọc TikTok
```python
# Scale cả 2 về 1080x960 (nửa màn hình 9:16)
# [top][bot]vstack[v] → 1080x1920
# Params: b_roll_video (str), split_ratio=0.5, audio_source ("main"|"b_roll"|"mix")
```
**Test thực tế:** Video podcast + video cắt cát/xà phòng → output 9:16

### Task 3.3 — `chromakey` | Tách nền màu
```python
# Pixel format bắt buộc: format=yuva420p trước colorkey
# [1:v]format=yuva420p,colorkey=color={hex}:similarity={s}:blend={b}[fg]
# [0:v][fg]overlay[out]
# Params: background_video, color="#00FF00", similarity=0.3, blend=0.1
```
**Test thực tế:** Video người đứng trước màn xanh → đặt lên nền mới

### Task 3.4 — `grid` | Lưới nhiều video
```python
# Dynamic filter_complex theo cols x rows
# Normalize từng video về cell_w x cell_h trước
# Xếp hàng bằng hstack, xếp cột bằng vstack
# Params: videos (list), cols, rows, output_width=1080, output_height=1920
```
**Test thực tế:** 4 video → grid 2x2

### Task 3.5 — `convert` | Chuyển định dạng
```python
CODEC_MAP = {
    "mp4":  ("libx264", "aac"),
    "webm": ("libvpx-vp9", "libopus"),
    "avi":  ("mpeg4", "mp3"),
    "mp3":  (None, "libmp3lame"),    # audio only (-vn)
    "aac":  (None, "aac"),           # audio only (-vn)
    "wav":  (None, "pcm_s16le"),     # audio only (-vn)
}
# Params: output_format (str)
```
**Test thực tế:** MP4 → MP3, MP4 → WebM

### Task 3.6 — `random_mirror` | Lật đoạn ngẫu nhiên
```python
# Tính n_segments = ceil(duration / segment_duration)
# Mỗi segment: random() < flip_probability → thêm ,hflip
# Xây filter_complex:
#   [0:v]trim={s}:{e},setpts=PTS-STARTPTS[,hflip][seg{i}]
# Concat tất cả → re-encode (KHÔNG -c copy, lỗi timestamp)
# Params: flip_probability=0.4, segment_duration=3.0
```
**Test thực tế:** Video 30s → một số đoạn bị lật, concat mượt

### Task 3.7 — Pipeline riêng: `split_video` và `extract_frames`
**Orchestrators mới:**
- `orchestrators/split_video_orchestrator.py` — dùng `-f segment`
- `orchestrators/extract_frames_orchestrator.py` — dùng `-vf fps=1/{interval}`
**Đây KHÔNG vào `low_level`** vì multi-output.

### Test Sprint 3 — Video Thực:
```bash
python main.py run ./test_input.mp4 --config-file ./pipelines/examples/hstack_test.json
python main.py run ./test_input.mp4 --config-file ./pipelines/examples/split_screen_tiktok.json
python main.py run ./test_input.mp4 --config-file ./pipelines/examples/chromakey_test.json
```
- [ ] Task 3.1 — hstack.py
- [ ] Task 3.2 — split_screen.py
- [ ] Task 3.3 — chromakey.py
- [ ] Task 3.4 — grid.py
- [ ] Task 3.5 — convert.py
- [ ] Task 3.6 — random_mirror.py
- [ ] Task 3.7 — split_video + extract_frames orchestrators

---

## 🟡 SPRINT 4 — Silence Cut + Auto Zoom (3–4 ngày)

### Task 4.1 — `silence_cut` pipeline (không cần silero-vad nặng)
**Chiến lược nhẹ (không cần torch):** Dùng FFmpeg silencedetect filter
```python
# Bước 1: ffmpeg -i input.mp4 -af silencedetect=n={db}dB:d={dur} -f null - 2>&1
# Bước 2: Parse output → extract silence timestamps
# Bước 3: Tính speech segments = inverse của silence
# Bước 4: FFmpeg trim+setpts+concat cho từng speech segment
# File: modules/ai/silence_remover.py
# Orchestrator: orchestrators/silence_cut_orchestrator.py
# Pipeline name: silence_cut
# KHÔNG cần silero-vad, torch → dependency-free!
```
**Test thực tế:** Video có nhiều khoảng lặng → output không còn khoảng lặng, nhịp nhanh hơn

### Task 4.2 — `auto_zoom` operation
```python
# FFmpeg zoompan filter:
# -vf "zoompan=z='if(lte(mod(on,{fps*interval}),{fps*trans}),
#       zoom+{step},if(lte(mod(on,{fps*interval}),{fps*trans}*2),zoom-{step},zoom))':
#       d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}"
# Params: interval_seconds=4, zoom_factor=1.1, transition_duration=0.3
# Contract: working_video
```
**Test thực tế:** Video 30s → zoom nhẹ mỗi 4 giây

- [ ] Task 4.1 — silence_remover.py (FFmpeg silencedetect, không torch)
- [ ] Task 4.2 — silence_cut_orchestrator.py
- [ ] Task 4.3 — auto_zoom.py
- [ ] Task 4.4 — Cập nhật low_level.py (+auto_zoom)

---

## 🎬 SPRINT 5 — Test Tích Hợp Toàn Diện Trên Video Thực (2–3 ngày)

### 5.1 — Tạo video test chuẩn
```bash
# Tạo video test tổng hợp 30s bằng FFmpeg (không cần file thật):
ffmpeg -f lavfi -i testsrc2=duration=30:size=1280x720:rate=30 \
       -f lavfi -i sine=frequency=440:duration=30 \
       -c:v libx264 -c:a aac test_input.mp4
```

### 5.2 — Bộ test JSON cho từng nhóm tính năng

**`pipelines/examples/test_suite_basic.json`** — Test 20 ops hiện có:
```json
{
  "pipeline_type": "low_level",
  "payload": {
    "operations": [
      { "name": "cut", "start": 0, "end": 20 },
      { "name": "speed", "factor": 1.2 },
      { "name": "scale", "w": 1080, "h": 1920 },
      { "name": "pad_border", "size": 20, "color": "white" },
      { "name": "audio_volume", "volume": 0.8 },
      { "name": "color_grade", "brightness": 0.1, "contrast": 1.1, "saturation": 1.2 },
      { "name": "visual_blur", "sigma": 1.5 }
    ]
  }
}
```

**`pipelines/examples/test_suite_portrait.json`** — Test video dọc TikTok:
```json
{
  "pipeline_type": "low_level",
  "payload": {
    "operations": [
      { "name": "blur_bg_portrait", "output_width": 1080, "output_height": 1920 },
      { "name": "pad_border", "size": 10, "color": "#000000" },
      { "name": "content_variant", "grain": 3, "hue_shift": 2.0 },
      { "name": "auto_zoom", "interval_seconds": 5 }
    ]
  }
}
```

**`pipelines/examples/test_suite_audio.json`** — Test audio operations:
```json
{
  "pipeline_type": "low_level",
  "payload": {
    "operations": [
      { "name": "audio_pitch", "semitones": 2, "preserve_tempo": true },
      { "name": "audio_normalize" },
      { "name": "audio_fade", "type": "in", "duration": 0.5 }
    ]
  }
}
```

**`pipelines/examples/test_suite_ai.json`** — Test AI pipelines:
```json
// silence_cut test
{ "pipeline_type": "silence_cut", "payload": { "min_silence_duration": 0.3 } }
```

### 5.3 — Script Test Tự Động
**File mới:** `scripts/test_all_features.ps1`
```powershell
# Chạy tất cả bộ test JSON và kiểm tra output tồn tại
$testCases = @(
    "test_suite_basic.json",
    "test_suite_portrait.json",
    "test_suite_audio.json",
    "workflow_dag_example.json",
    "semantic_silence_cut.json"
)
foreach ($test in $testCases) {
    Write-Host "Testing: $test" -ForegroundColor Cyan
    python main.py run .\test_input.mp4 --config-file ".\pipelines\examples\$test"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ PASS: $test" -ForegroundColor Green
    } else {
        Write-Host "❌ FAIL: $test" -ForegroundColor Red
    }
}
```

### 5.4 — Test API End-to-End
```powershell
# Khởi động server:
python main.py api

# Test từng pipeline qua HTTP:
curl -X POST http://localhost:8000/jobs `
  -H "X-API-Key: test-key" `
  -H "Content-Type: application/json" `
  -d '{"input_uri":"file:///path/to/test_input.mp4","pipeline_type":"silence_cut","payload":{"min_silence_duration":0.5}}'
```

- [ ] Task 5.1 — Tạo video test synthetic
- [ ] Task 5.2 — 5 file JSON test suite
- [ ] Task 5.3 — scripts/test_all_features.ps1
- [ ] Task 5.4 — Pytest integration tests cho các ops mới

---

## 📊 Tổng Kết Sprint

| Sprint | Thời Gian | Kết Quả |
|---|---|---|
| Sprint 1 | 1–2 ngày | workflow + semantic_edit có thể gọi qua API |
| Sprint 2 | 3–4 ngày | +7 operations → **27 ops tổng** |
| Sprint 3 | 4–5 ngày | +6 operations → **33 ops tổng** + 2 pipelines mới |
| Sprint 4 | 3–4 ngày | silence_cut (không cần torch!) + auto_zoom |
| Sprint 5 | 2–3 ngày | Test suite đầy đủ, pass 100% trên video thực |

**Tổng: ~2–3 tuần → đạt v3.0 với 33 operations + 8 pipelines đã test thực tế**

---

## ✅ Definition of Done (Tiêu chí Hoàn Thành)

Mỗi tính năng chỉ được tick ✅ khi:
1. **Code tồn tại** — file `.py` đã được tạo
2. **Đăng ký** — vào `low_level.py` hoặc `factory.py` 
3. **Test unit pass** — `python -m pytest` không có failure mới
4. **Test video thực** — chạy được `python main.py run` với config JSON tương ứng và output file hợp lệ
5. **Không crash** — không có unhandled exception, không treo

---

*Sprint plan này executable ngay. Bắt đầu từ Sprint 1 → hoàn thành theo thứ tự.*
