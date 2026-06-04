# Phân Tích Test Run — `full_evidence_20260512_1054_patched`

> **So sánh**: Run trước (10/05) → Run mới (12/05)

---

## Tổng Quan

| Metric | Run 10/05 | Run 12/05 | Delta |
|---|---|---|---|
| **Pass / Total** | 53 / 58 | **60 / 61** | +7 PASS, +3 cases |
| **Pass Rate** | 91.4% | **98.4%** | +7 điểm |
| **Fail** | 5 | **1** | -4 |
| **Events** | 2,886 | 2,932 | +46 |
| **FFprobe Evidence** | ~55 files | **71 files** | +16 |
| **Unit Tests** | 134 | **154** | +20 |

---

## Các Bug Đã Fix Thành Công

### ✅ 1. Webhook Batch — job.failed callback
- **Trước**: `WB_CALLBACK_FAILED_STUCK` — job unknown_op kẹt `running`, không có `job.failed` callback
- **Sau**: Webhook callbacks section ghi rõ cả 3 events đã nhận: `job.completed`, `job.failed`, `job.cancelled`
- **Fix**: Pipeline error boundary wrap `_build_workflow()` trong try/except → exception luôn đến terminal state

### ✅ 2. WB_BATCH_ALL batch branch
- **Trước**: FAIL vì thiếu failed callback → batch branch không chạy tiếp
- **Sau**: `WB_BATCH_ALL` PASS — verification `batch pass 4/4`
- **Root cause**: Fix #1 cascade — failed job có callback → batch branch nhận event → tiếp tục

### ✅ 3. WB_CALLBACK_EVENTS
- **Trước**: FAIL — thiếu `job.failed` event
- **Sau**: PASS — `all_callbacks_received`
- Callbacks observed:
  - `job.completed` → job `6311237c` status `done`
  - `job.failed` → job `300857b4` status `failed` (error: `overlay operation requires overlay_path`)
  - `job.cancelled` → job `21062b6a` status `cancelled`

### ✅ 4. Cancel flow
- `NEG_03_CANCEL_RUNNING`: PASS — job cancelled correctly
- Cancel callback có structured error detail: `code: CANCELLED`, `step: blur_bg_portrait`

### ✅ 5. Job State Contract implemented
Code evidence:
- `IllegalStateTransition` exception: ✅ defined in `core/exceptions.py`
- `JobStatus.is_terminal` + `can_transition_to()`: ✅ in `core/models.py`
- `TERMINAL_JOB_STATUSES` + `JOB_STATUS_TRANSITIONS`: ✅ formal maps
- `fail_overlong_jobs()`: ✅ separate method (3 repos + batch_engine integration)
- `terminal_notified` flag: ✅ idempotent webhook delivery
- `JobError.stage` + `.operation` fields: ✅ failure taxonomy

---

## Lỗi Còn Lại: 1 FAIL

### ❌ RV_P02 — `dubbing_burned` (dubbing + burn_subtitles)

```
Status: FAIL
Verification: job_status_failed
Error: 503, message='Invalid response status',
       url='wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?...'
Job ID: b9d73499-ceb4-45c4-9d8a-690bca242277
```

**Root cause**: Edge TTS websocket trả HTTP 503 — **external service failure**, không phải bug code.

**Đánh giá**:
- RV_P01 (dubbing vi, không burn subtitles) → PASS ✅ — chứng tỏ dubbing pipeline hoạt động
- RV_P02 chỉ khác `burn_subtitles: true` — lỗi xảy ra ở TTS step, trước subtitle burn
- Đây là **intermittent failure** do Edge TTS rate limiting / service instability
- Job đã đúng terminal state (`failed`) với error message rõ ràng → **contract hoạt động đúng**

**Fix đề xuất** (Phase 1.3 trong roadmap):
- TTS retry 3 lần với exponential backoff
- Fallback: `edge-tts` → `gtts` nếu 503 persistent
- Mark TTS errors `retriable: true` (đã có trong error taxonomy)

---

## Contract Implementation Status

| Contract Item | Status | Evidence |
|---|---|---|
| `JobStatus.is_terminal` | ✅ Done | `core/models.py:21` |
| `can_transition_to()` | ✅ Done | `core/models.py:24` |
| `IllegalStateTransition` exception | ✅ Done | `core/exceptions.py:39` |
| `fail_overlong_jobs()` tách riêng | ✅ Done | 3 repos + batch_engine |
| `terminal_notified` flag | ✅ Done | `core/models.py:141` |
| Webhook idempotency | ✅ Done | Check `terminal_notified` before dispatch |
| `JobError.stage` + `.operation` | ✅ Done | `core/models.py:70-71` |
| Error builder helpers | ✅ Done | `unknown_operation()`, `invalid_params()` |
| Extended `JobErrorCode` | ✅ Done | 5 new codes added |
| State contract tests | ✅ Done | 10 tests in `test_job_state_contract.py` |
| Webhook dispatch tests | ✅ Done | 13 tests in `test_webhook_dispatch.py` |

### ⚠️ Chưa tìm thấy trong code

| Item | Status | Note |
|---|---|---|
| `_assert_transition()` guard | ❌ Not found | `can_transition_to` defined nhưng chưa thấy guard call trong `complete_job`/`fail_job` |
| Worker ownership check (`worker_id` match) | ⚠️ Cần verify | grep không tìm thấy explicit guard |
| `update_progress()` terminal rejection | ⚠️ Cần verify | Cần check implementation |
| `can_cancel` / `can_retry` in API response | ⚠️ Cần verify | Cần check `api/schemas.py` |

---

## So Sánh Theo Nhóm

| Group | Run 10/05 | Run 12/05 |
|---|---|---|
| 00 Smoke | 1/1 ✅ | 1/1 ✅ |
| 01 Low-Level Matrix | 35/35 ✅ | 35/35 ✅ |
| 02 Pipeline AI | 13/15 ⚠️ | **14/15** ⚠️ (was 2 TTS fail, now 1) |
| 03 Webhook Batch | 3/6 ❌ | **6/6** ✅ |
| 04 Negative Recovery | 4/4 ✅ | 4/4 ✅ |

**Highlight**: Webhook Batch từ 3/6 → **6/6** — đây là nhóm quan trọng nhất đã fix.

---

## Kết Luận

### Tình trạng hệ thống: 🟢 Gần Production-Ready

1. **Job lifecycle**: State machine contract hoạt động. Mọi exception đều đến terminal state.
2. **Webhook delivery**: 3/3 callbacks (completed, failed, cancelled) đều received.
3. **Zombie prevention**: `fail_overlong_jobs()` tách riêng, `terminal_notified` idempotent.
4. **154 unit tests** pass — +20 so với lần trước.

### Việc cần làm tiếp

| Priority | Item | Effort |
|---|---|---|
| 🔴 P0 | Thêm `_assert_transition()` guard calls trong `complete_job()`/`fail_job()` | 30 phút |
| 🔴 P0 | Worker ownership check (`worker_id` match) trong terminal mutations | 30 phút |
| 🟡 P1 | TTS retry/fallback để fix RV_P02 | 2-3 giờ |
| 🟡 P1 | `can_cancel`/`can_retry` trong API response | 1 giờ |
| 🟢 P2 | Thêm race condition tests (contract test matrix chưa đủ 30 tests) | 2 giờ |
