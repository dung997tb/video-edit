# Project Issues Review - 2026-04-21

## Scope
Review lai toan bo du an theo yeu cau production (API public internet, multi-replica worker, cache/resume, ffmpeg lifecycle, output duration business rule).

## Issues va Trang Thai

1. Lease fencing thieu khi ghi progress/complete/fail (Critical)
- Risk: worker cu sau khi mat lease co the ghi de state cua worker moi.
- Fix: them `worker_id` fencing cho `update_progress`, `complete_job`, `fail_job` trong `JobManager` + repository implementations; `PipelineRunner` truyen `worker_id` khi ghi state.
- Status: Fixed.

2. `voice_sync_retry` khong publish artifacts vao step manifest (High)
- Risk: cache resume cross-replica co the restore thieu file cho step retry.
- Fix: `VoiceSyncRetryModule` nay aggregate artifacts tu segmenter/tts/sync va luon include `synced_audio`.
- Status: Fixed.

3. Upload API doc file lon vao RAM + call storage blocking trong async route (High)
- Risk: OOM/latency spike khi public traffic.
- Fix: doi sang stream theo chunk (1MB), hash incremental, gioi han `API_UPLOAD_MAX_BYTES`, upload qua `run_in_threadpool`, cleanup temp file.
- Status: Fixed.

4. Client co the inject `source_sha256` tuy y (Medium)
- Risk: cache identity poisoning/collision logic.
- Fix: mac dinh khong cho direct `source_sha256`; chi cho phep neu bat `API_ALLOW_CLIENT_SOURCE_SHA256=true`; co validate sha256 hex.
- Status: Fixed.

5. Preflight DB chua check columns/indexes bat buoc (Medium)
- Risk: pass preflight nhung schema/index production chua day du.
- Fix: mo rong `verify_jobs_schema_requirements` de check `missing_columns`, `missing_indexes`; bo sung index cho claim/query path.
- Status: Fixed.

6. Public API cho phep `input_path` doc path local host (Security hardening)
- Risk: surface tang cao khi API internet-facing.
- Fix: mac dinh khoa `input_path` tren API (`API_ALLOW_INPUT_PATH=false`), tra ve 400 neu client gui `input_path`.
- Status: Fixed.

7. Output final phai giu nguyen duration video goc (Business rule)
- Risk cu: `-shortest` lam clip bi rut ngan theo audio.
- Fix: remux moi dung `apad + atrim=duration=<video_duration>` theo ffprobe duration cua video goc.
- Status: Fixed.

8. TTS overflow con unresolved sau retry CPS (Quality hardening)
- Risk: voice van co the bi trim khi segment qua dai.
- Fix: them fallback re-segmentation that su trong `voice_sync_retry.py`:
  - neu van overflow sau pass tighten CPS, split lai segment overflow theo text/time slot,
  - rerun TTS + voice sync them 1 pass.
- Status: Fixed.

9. Task P1 benchmark/canary chua co du artifact tai lieu (Delivery completeness)
- Risk: kho verify target default va smoke profile trong CI.
- Fix:
  - them `benchmarks/worker_poll_benchmark.py` + `benchmarks/README.md` (co command + snapshot ket qua),
  - them `pipelines/examples/canary_smoke.json` va `workflows/canary_smoke.json`.
- Status: Fixed.

## Validation
- `python -m unittest discover -s tests -v`
- Ket qua: 61 passed, 7 skipped (skip do thieu fastapi stack / ffmpeg trong local env).
