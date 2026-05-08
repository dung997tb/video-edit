# AI Video Automation Engine - Implementation Plan (Updated 2026-05-08)

## Current Status
- Overall: P0/P1/P2 code scope is implemented for single-repo delivery.
- Tests: `66 passed` in current local environment.
- Readiness: code-level production hardening is complete; remaining items are infra rollout/verification tasks.

## Completed Scope

### Phase 0 - Fix and Setup
- [x] `modules/registry.py` uses `cls.NAME` registration pattern.
- [x] `modules/base.py` has stable `NAME` convention.
- [x] `config/settings.py` includes runtime/cache directories and worker/API toggles.
- [x] `core/file_manager.py` has numbered `STEP_NAMES` and deterministic `step_file()`.
- [x] Package init files are in place (`core`, `modules`, `api`).

### Phase 1 - Core Foundation
- [x] `core/context.py` pipeline context wiring.
- [x] `core/retry.py` exponential retry with `JobCancelledError` non-retryable.
- [x] `core/cache.py` operation cache + step idempotency cache.
- [x] `core/pipeline.py` resume/skip behavior from step cache.
- [x] `core/job_manager.py` lease, pid, cancel, heartbeat + worker fencing writes.
- [x] `core/batch_engine.py` worker loop + `ThreadPoolExecutor(max_workers=N)` + adaptive polling.

### Phase 2 - Atomic Modules
- [x] Video ops implemented and wired into low-level pipeline.
- [x] Audio ops package (`audio_trim`, `audio_speed`, `audio_volume`, `audio_fade`, `audio_normalize`).
- [x] Visual ops package (`visual_blur`, `visual_sharpen`, `visual_grayscale`, `visual_vignette`).

### Phase 3 - AI Modules
- [x] `transcriber.py` compound cache key.
- [x] `translator.py` compound cache key.
- [x] `segmenter.py` strategy support (`chars`, `slot_adaptive`).
- [x] `subtitle_gen.py` and `subtitle_burn.py`.
- [x] `tts.py`, `voice_sync.py`, `audio_mixer.py`, `dubbing.py`.
- [x] `voice_sync_retry.py` second-pass tighter segmentation + unresolved overflow resplit fallback.

### Phase 4 - API and Orchestrators
- [x] API enqueue/cancel routes and worker boot behavior.
- [x] Orchestrators package and runtime wiring.
- [x] API auth middleware (`x-api-key`, `Authorization: Bearer`).
- [x] Pipeline type validation at API layer.
- [x] Public API hardening:
  - `input_path` disabled by default for remote callers (`API_ALLOW_INPUT_PATH=false`).
  - client-provided `source_sha256` disabled by default (`API_ALLOW_CLIENT_SOURCE_SHA256=false`).
  - upload endpoint streams by chunk with size limit (`API_UPLOAD_MAX_BYTES`).

### Phase 5 - Config, Schema, Docs
- [x] `supabase/schema.sql` includes lease RPCs + `request_cancel_job`.
- [x] Added schema verification RPC checks for required table/trigger/RPC/columns/indexes.
- [x] Added benchmark harness and docs:
  - `benchmarks/worker_pool_benchmark.py`
  - `benchmarks/worker_poll_benchmark.py`
  - `benchmarks/README.md`
- [x] Added canary smoke configs:
  - `pipelines/examples/canary_smoke.json`
  - `workflows/canary_smoke.json`
- [x] Added deployment smoke utility:
  - `scripts/smoke_prod.ps1` (health + enqueue + running-cancel + terminal-state validation)
- [x] Updated `requirements.txt`, `README.md`, `.env.example`, `main.py`.

### Phase 6 - Upgrade Proposal 2026-05-08
- [x] Critical reliability fixes:
  - streaming SHA-256 in `core/cache.py`.
  - resettable service cache via `reset_services()`.
  - logged Supabase cancel-RPC fallback.
  - cancel-safe, timeout-aware ffprobe calls in voice sync and remux.
  - explicit retry lambda binding in pipeline execution.
- [x] Observability and API improvements:
  - `GET /jobs/{job_id}/stream` SSE progress endpoint.
  - structured `JobError` / `error_detail` on failed jobs.
  - optional Prometheus `/metrics` endpoint and job metrics.
  - optional OpenTelemetry step spans.
- [x] TTS and feature expansion:
  - TTS backend abstraction for `edge-tts`, OpenAI, and Google Cloud REST TTS.
  - parallel TTS segment generation with cancel-safe multi-process registry support.
  - `subtitle` / `subtitle-only`, `audio-extract` / `audio_extract`, and `multilang-dubbing` pipelines.
  - per-job `cache_bust` / `bypass_cache`.
  - background music URL/volume and ducking controls.
- [x] Scale/security foundations:
  - priority field and priority-aware claiming in memory and Supabase.
  - optional terminal-state webhooks.
  - per-key in-memory API rate limiting.
  - minimal `/admin` dashboard.

## Review Items From `.agent/Vn-mc-Ghi.csv`

| Item | Severity | Status | Note |
|---|---|---|---|
| Worker poll interval may cause lag | Medium | Closed | Adaptive polling implemented + benchmarked (`0.2 -> 1.0` backoff). |
| ThreadPool may be suboptimal for CPU-heavy tasks | Medium | Closed (decision) | Benchmark harness added; default kept ThreadPool for ffmpeg-heavy I/O workload. |
| `SIGTERM` behavior on Windows | Low | Closed | Cancel path uses terminate/kill through process registry. |
| No explicit timeline in plan | High | Open (External PM) | Requires rollout owner/date decision outside codebase. |
| TTS overflow re-segmentation incomplete | Medium | Closed | Added unresolved overflow resplit fallback in `voice_sync_retry.py`. |

## Remaining External Task Board

### Production Rollout (cannot be completed from local repo only)
- [ ] Apply latest `supabase/schema.sql` to production database.
- [ ] Run real multi-replica smoke in deployment environment (`>=2 api`, `>=2 worker`).
- [ ] Run auth tests in CI lane with full FastAPI stack installed (no skip).
- [ ] Set production secrets and env:
  - `API_SECRET_KEY` strong secret
  - `JOB_BACKEND=supabase`
  - `ARTIFACT_STORE_BACKEND=supabase`
  - `API_EMBEDDED_WORKER=false`

## Deployment Defaults
- Production:
  - `JOB_BACKEND=supabase`
  - `ARTIFACT_STORE_BACKEND=supabase`
  - `API_EMBEDDED_WORKER=false`
  - `API_ALLOW_INPUT_PATH=false`
  - `API_ALLOW_CLIENT_SOURCE_SHA256=false`
- Local dev:
  - `API_EMBEDDED_WORKER=true`

---
Last updated: 2026-05-08
