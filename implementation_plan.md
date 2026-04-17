# AI Video Automation Engine - Implementation Plan (Updated 2026-04-15)

## Current Status
- Overall: core architecture and main features are implemented.
- Tests: `32 passed`, `5 skipped` (skipped auth tests when `fastapi` stack is not installed in local test env).
- Readiness: good for dev/staging; production rollout still needs final infra validation.

## Completed Scope

### Phase 0 - Fix and Setup
- [x] `modules/registry.py` uses `cls.NAME` registration pattern.
- [x] `modules/base.py` has stable `NAME` convention.
- [x] `config/settings.py` includes `cache_dir`.
- [x] `core/file_manager.py` has numbered `STEP_NAMES` and `step_file()`.
- [x] `core/__init__.py` and `modules/__init__.py`.

### Phase 1 - Core Foundation
- [x] `core/context.py` and pipeline context wiring.
- [x] `core/retry.py` with retry and exponential backoff.
- [x] `core/cache.py` with operation cache + step-level idempotency cache.
- [x] `core/pipeline.py` with step resume/skip behavior.
- [x] `core/job_manager.py` with lease, pid, cancel, heartbeat flows.
- [x] `core/batch_engine.py` worker loop + `ThreadPoolExecutor(max_workers=N)`.

### Phase 2 - Atomic Modules
- [x] Video ops implemented and wired into low-level pipeline.
- [x] Audio ops package (`audio_trim`, `audio_speed`, `audio_volume`, `audio_fade`, `audio_normalize`).
- [x] Visual ops package (`visual_blur`, `visual_sharpen`, `visual_grayscale`, `visual_vignette`).

### Phase 3 - AI Modules
- [x] `transcriber.py` compound cache key.
- [x] `translator.py` compound cache key.
- [x] `segmenter.py` added and wired in dubbing flow.
- [x] `subtitle_gen.py` and `subtitle_burn.py`.
- [x] `tts.py`, `voice_sync.py`, `audio_mixer.py`, `dubbing.py`.

### Phase 4 - API and Orchestrators
- [x] API enqueue/cancel routes and worker boot behavior.
- [x] Orchestrators package and runtime wiring.
- [x] API auth middleware (`x-api-key` and `Authorization: Bearer`).
- [x] Pipeline type validation at API layer.

### Phase 5 - Config and Docs
- [x] `supabase/schema.sql` (including lease RPCs + `request_cancel_job`).
- [x] `workflows/*.json` presets.
- [x] `pipelines/examples/*.json` examples.
- [x] `requirements.txt`, `README.md`, `main.py` updated.

## Extra Fixes Completed After Initial Plan
- [x] `SupabaseArtifactStore.exists()` now paginates and safely handles missing folders.
- [x] `PipelineRunner` validates `input_path` existence early.
- [x] TTS event-loop handling switched to explicit `new_event_loop()` lifecycle.
- [x] Supabase cancel moved to atomic RPC (with backward-compatible fallback path).
- [x] Voice sync overflow fallback improved: apply max allowed speed before trim to preserve more spoken content.

## Review Input From `.agent/Vn-mc-Ghi.csv`

| Item | Severity | Status | Note |
|---|---|---|---|
| worker poll interval (`time.sleep(1)`) may cause lag | Medium | Open | Add adaptive polling or realtime strategy benchmark. |
| ThreadPool may be suboptimal for CPU-heavy tasks | Medium | Open | Current design is acceptable for subprocess-heavy flow; still needs benchmark for heavy CPU mix. |
| `SIGTERM` behavior on Windows | Low | Closed | Current cancel path uses process terminate/kill in registry; cross-platform behavior improved. |
| No explicit timeline in plan | High | Open | Add milestone dates and owners for rollout. |
| TTS edge-case 3 re-segmentation description incomplete | Medium | Improved | Overflow handling now keeps more spoken content with max-speed-before-trim fallback; semantic re-TTS split is still optional future work. |

## Next Task Board

### P0 (Before production go-live)
- [ ] Apply latest `supabase/schema.sql` to production DB and verify RPCs:
  `claim_jobs`, `release_stale_leases`, `request_cancel_job`.
- [ ] Run smoke test in real multi-replica environment (`api` replicas + `worker` replicas).
- [ ] Run API auth tests in an environment with `fastapi` dependencies installed (no skip).

### P1 (Stability and performance)
- [ ] Add integration tests for real `ffmpeg` flows: cancel mid-step, lease-expire resume, cache hit correctness.
- [ ] Benchmark worker polling (`1.0s`, `0.5s`, adaptive backoff) and document target.
- [ ] Benchmark ThreadPool vs ProcessPool for mixed workloads and keep measured default.

### P2 (Quality improvements)
- [ ] Implement stronger TTS overflow fallback (true text re-segmentation when overflow exceeds stretch limit).
- [ ] Add end-to-end canary workflow JSON for CI smoke execution.

## Deployment Defaults
- Production: `JOB_BACKEND=supabase`, `ARTIFACT_STORE_BACKEND=supabase`, `API_EMBEDDED_WORKER=false`.
- Local dev: `API_EMBEDDED_WORKER=true` for convenience.
- Security: `API_AUTH_ENABLED=true` with strong `API_SECRET_KEY`.

---
Last updated: 2026-04-15
