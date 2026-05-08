# 📋 PLANS.MD — Platform Roadmap v3.0
## AI Video Automation Engine → Resumable Declarative AI Media Workflow Engine

> Cập nhật: 2026-05-08
> **Định vị sản phẩm:** Không phải "CapCut OSS". Là **Temporal for AI media workflows**.
> **Nguyên tắc:** Không rewrite. Thêm abstraction layer phía trên hệ thống hiện có.

---

## 🧭 Tầm Nhìn Sản Phẩm

Hệ thống hiện tại đã rất mạnh ở tầng thực thi:
✅ Job queue + worker pool | ✅ Step cache + resume | ✅ Cancel-safe FFmpeg subprocess
✅ Artifact store | ✅ Retry + idempotency | ✅ Multi-replica safe

**Điều còn thiếu** để thành platform thực sự:
- ❌ Workflow graph (DAG) — pipeline hiện là list hardcoded modules
- ❌ Timeline/composition model — B-roll, karaoke, scene edit sẽ hardcode FFmpeg
- ❌ Plugin system — mỗi backend mới phải sửa core code
- ❌ Semantic AI layer — chưa "hiểu" nội dung video, chỉ transform cơ học
- ❌ Asset lineage — không theo dõi quan hệ giữa các artifact

---

## 🗺️ Roadmap 5 Tầng

```
Tầng 5: Semantic AI Layer        (scene detect, pacing, hooks)
Tầng 4: Asset Graph + Events     (lineage, event bus)
Tầng 3: Plugin Ecosystem         (nodes, tts, renderers, analyzers)
Tầng 2: Timeline Model           (tracks, clips, composition)
Tầng 1: Workflow DAG Core        ← QUAN TRỌNG NHẤT
────────────────────────────────────────────────────
Tầng 0: Hệ thống hiện có (giữ nguyên, không rewrite)
```

---

## ⚡ PHASE 0 — Workflow DAG Core (Quan Trọng Nhất)
**Ưu tiên: 🔴 Cao nhất | Thời gian: 2–3 tuần**

### Vấn đề hiện tại
Pipeline hiện tại là `list[BaseModule]` hardcoded trong từng orchestrator. Muốn thêm retry/parallelism/condition/dependency phải sửa thẳng vào core. Không scale được.

### Mục tiêu
Cho phép định nghĩa workflow dưới dạng **declarative spec** (JSON/YAML):

```yaml
# Ví dụ: dubbing workflow dưới dạng DAG
nodes:
  transcribe:
    type: ai.transcribe
    retry: 3

  translate:
    type: ai.translate
    depends_on: [transcribe]
    params: { target_language: vi }

  tts:
    type: ai.tts
    depends_on: [translate]
    parallelism: 5

  render:
    type: media.render
    depends_on: [tts]
```

### Files cần tạo

```
core/
  workflow/
    spec.py          # WorkflowSpec, NodeSpec, NodeResult dataclasses
    dag.py           # DAGRunner: topological sort + execute theo thứ tự
    registry.py      # NodeRegistry: đăng ký node type → class
    compat.py        # Compatibility layer: compile pipeline cũ → WorkflowSpec
```

**`core/workflow/spec.py`**
```python
@dataclass
class NodeSpec:
    id: str
    type: str                      # "ai.transcribe", "media.cut", v.v.
    depends_on: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    retry: int = 1
    parallelism: int = 1

@dataclass
class WorkflowSpec:
    nodes: dict[str, NodeSpec]
    metadata: dict = field(default_factory=dict)

@dataclass
class NodeResult:
    node_id: str
    status: Literal["pending", "running", "done", "failed", "skipped"]
    artifacts: dict[str, str] = field(default_factory=dict)  # name → path
    error: str | None = None
```

**`core/workflow/dag.py`**
```python
class DAGRunner:
    def __init__(self, spec: WorkflowSpec, registry: NodeRegistry): ...
    def run(self, context, services) -> dict[str, NodeResult]: ...
    def _topological_sort(self) -> list[list[str]]: ...  # Trả về batches song song
    def _can_run_parallel(self, batch: list[str]) -> bool: ...
```

**`core/workflow/compat.py`** — Compatibility layer (QUAN TRỌNG để không rewrite):
```python
def pipeline_to_workflow(modules: list[BaseModule]) -> WorkflowSpec:
    """Compile pipeline list cũ thành WorkflowSpec tương đương."""
    # Mỗi module → 1 node, depends_on = node trước
    ...
```

### Kết quả sau Phase 0
- Orchestrator cũ **vẫn chạy bình thường** qua compat layer
- Orchestrator mới có thể viết dưới dạng YAML/JSON spec
- Nền tảng để Phase tiếp theo thêm parallelism, conditional branching

---

## 📐 PHASE 1 — Timeline Model
**Ưu tiên: 🟠 Cao | Thời gian: 1–2 tuần | Làm SAU Phase 0**

### Vấn đề hiện tại
Nếu bắt tay làm B-roll, karaoke subtitle, split-screen **ngay bây giờ** → mỗi feature sẽ là 1 đống FFmpeg command hardcode. Khó bảo trì, khó test, không tái sử dụng được.

### Giải pháp: Timeline Model trước, FFmpeg render sau

```json
{
  "duration": 120.5,
  "tracks": [
    {
      "type": "video",
      "clips": [
        { "source": "main.mp4", "start": 0, "end": 30, "track_start": 0 },
        { "source": "broll.mp4", "start": 5, "end": 10, "track_start": 25, "opacity": 0.8 }
      ]
    },
    {
      "type": "audio",
      "clips": [
        { "source": "dubbed.aac", "start": 0, "end": 120.5, "volume": 1.0 },
        { "source": "bgm.mp3", "start": 0, "end": 120.5, "volume": 0.15 }
      ]
    },
    {
      "type": "subtitle",
      "clips": [
        { "text": "Hello world", "start": 1.2, "end": 3.5, "style": "karaoke" }
      ]
    }
  ]
}
```

### Files cần tạo

```
core/
  timeline/
    model.py         # Timeline, Track, Clip, SubtitleClip dataclasses
    compiler.py      # TimelineCompiler: Timeline → FFmpeg filter_complex
    builder.py       # TimelineBuilder: helper API để build timeline
```

### Lợi ích
Sau khi có Timeline Model, các tính năng sau sẽ **không viết FFmpeg trực tiếp** nữa:
- `auto_broll` → thêm Clip vào video track tại timestamp
- `karaoke_subtitle` → thêm SubtitleClip với style vào subtitle track
- `split_screen` → 2 Clip chồng nhau với opacity + layout
- `silence_cut` → xóa Clip gaps khỏi track

---

## 🔌 PHASE 2 — Plugin System
**Ưu tiên: 🟡 Trung bình | Thời gian: 1–2 tuần | Làm SAU Phase 0+1**

### Cấu trúc thư mục mới

```
plugins/
  nodes/              # Node types đăng ký vào NodeRegistry
    media_cut.py
    media_concat.py
    ...
  tts/                # TTS backends (đã có pattern, cần chuẩn hóa)
    edge_tts.py
    openai_tts.py
    google_tts.py
  translators/
  renderers/
  analyzers/
```

### Plugin Manifest

```json
{
  "name": "openai-tts",
  "version": "1.0.0",
  "type": "tts",
  "entrypoint": "plugins.tts.openai_tts.OpenAITTSBackend",
  "config_schema": {
    "OPENAI_API_KEY": { "type": "string", "required": true },
    "OPENAI_TTS_MODEL": { "type": "string", "default": "tts-1" }
  }
}
```

### Mục tiêu
Người khác (hoặc bản thân sau này) thêm TTS backend mới, renderer mới, analyzer mới **mà không sửa core code**.

---

## 🧠 PHASE 3 — Semantic AI Layer
**Ưu tiên: 🟡 Trung bình | Thời gian: 3–4 tuần**

Đây mới là "AI-native editing". **Output của Semantic Layer không phải video** — mà là **Timeline edits** hoặc **Workflow patches**.

### Semantic Analyzers cần build

| Analyzer | Input | Output | Độ Khó |
|---|---|---|---|
| `silence_detector` | audio/video | `list[(start, end)]` khoảng lặng | ⭐⭐ |
| `pacing_analyzer` | transcript | điểm pacing + gợi ý cắt | ⭐⭐⭐ |
| `hook_detector` | transcript + audio | timestamp đoạn "hook" (30s đầu) | ⭐⭐⭐ |
| `scene_detector` | video | `list[(start, end)]` mỗi cảnh | ⭐⭐⭐ |
| `speaker_detector` | audio | diarization: ai nói khi nào | ⭐⭐⭐⭐ |
| `highlight_extractor` | video + audio | top N đoạn hay nhất | ⭐⭐⭐⭐ |

### Semantic Commands (API mới)

```json
// Thay vì gọi operation cụ thể, gọi intent:
{
  "pipeline_type": "semantic_edit",
  "payload": {
    "command": "make_tiktok_short",
    "target_duration": 60,
    "style": "fast_paced"
  }
}
// Engine tự phân tích video → tạo Timeline → render
```

---

## 🗄️ PHASE 4 — Asset Graph + Event Bus
**Ưu tiên: 🟢 Thấp | Thời gian: 2–3 tuần**

### Asset Lineage
Theo dõi quan hệ cha-con giữa các artifact:
```
source_video.mp4
  ├── transcript_v1.json      (từ transcriber)
  ├── subtitles_vi.srt        (từ translator)
  ├── dubbed_vi.mp4           (từ voice_sync)
  └── clips/
        ├── highlight_001.mp4
        └── highlight_002.mp4
```

### Event Bus (bắt đầu in-memory, sau mới Redis)
```
Events:
  video.uploaded
  transcribe.done
  subtitle.ready
  render.done
  job.failed
  job.cancelled
```

---

## 📦 Operations Ecosystem (Làm Xuyên Suốt)
**Chạy song song với các Phase trên, không chặn nhau**

Sau khi có **Timeline Model** (Phase 1), các operation này trở thành **Timeline Nodes** thay vì hardcoded FFmpeg:

### Nhóm 1A — Single I/O, làm ngay (không cần Timeline Model)
- `pad_border`, `blur_bg_portrait`, `loop`, `filter_duration`, `delogo`, `audio_pitch`, `content_variant`

### Nhóm 1B — Multi-input, làm sau khi có Timeline Model
- `hstack`, `split_screen`, `chromakey`, `grid`, `convert`, `random_mirror`

### Nhóm 2 — AI Retention (cần Semantic Layer)
- `silence_cut` ← `silence_detector` semantic node
- `karaoke_subtitle` ← `SubtitleClip` trong Timeline Model
- `auto_zoom` ← `pacing_analyzer` semantic node

### Nhóm 3 — Content Variant Tools (đổi tên từ "Anti-Reup")
- `content_variant` — Tạo biến thể kỹ thuật hợp pháp cho đa nền tảng
- `platform_reframe` — Tự động reframe từ 16:9 → 9:16 → 1:1

### Nhóm 4 — AI Nâng Cao (cần spike performance)
- `face_track_portrait` — Cần đo benchmark trên CPU trước
- `auto_broll` — Phụ thuộc Timeline Model + Semantic Layer

---

## 📊 Số Liệu Mục Tiêu

| | v2.0 (hiện tại) | v3.0 (sau roadmap) |
|---|---|---|
| Architecture | Pipeline list | Workflow DAG |
| Operations | 20 | 34 |
| AI Pipelines | 5 | 8 |
| Semantic Commands | 0 | 5+ |
| Plugin types | 1 (TTS) | 5+ |

---

## ✅ Thứ Tự Thực Hiện

```
Tuần 1–3:   Phase 0 — WorkflowSpec + DAGRunner + compat layer
Tuần 4–5:   Phase 1 — Timeline Model + TimelineCompiler
Tuần 5–6:   Operations Nhóm 1A (7 ops đơn giản, chạy song song)
Tuần 7–8:   Phase 2 — Plugin System
Tuần 8–9:   Operations Nhóm 1B (sau khi có Timeline Model)
Tuần 9–12:  Phase 3 — Semantic Analyzers (silence → pacing → hook)
Tuần 12+:   Phase 4 — Asset Graph + Event Bus
```

---

## ⚠️ Những Gì KHÔNG Làm

- ❌ Không rewrite job queue, worker, cache, artifact store — giữ nguyên
- ❌ Không nhảy thẳng vào Temporal/Airflow — quá nặng cho giai đoạn này
- ❌ Không làm frontend/UI trước khi core ổn định
- ❌ Không bỏ tên "Anti-Reup" mà thay bằng language hợp pháp

---

*Khi hoàn thành roadmap này: project sẽ là **Resumable, declarative AI video workflow engine** — có thể cạnh tranh với Creatomate, Shotstack về kiến trúc, nhưng open và flexible hơn nhiều.*
