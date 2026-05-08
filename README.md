# AI Video Engine

Multi-replica-safe video automation scaffold with dedicated worker role, Supabase-backed queue/storage adapters, step-level idempotency, and ffmpeg subprocess control.

## What is included

- FastAPI API that enqueues and cancels jobs, with an optional embedded worker for local/dev boot.
- Worker loop with `ThreadPoolExecutor(max_workers=N)` and lease-based claiming.
- Shared artifact/cache abstractions with local and Supabase backends.
- Step cache resume support for retrying a failed job without re-running completed steps.
- Loudness-normalized audio mixing with deterministic file naming.
- Atomic low-level operations for video/audio/visual:
  `cut`, `speed`, `flip`, `crop`, `rotate`, `scale`, `concat`, `overlay`, `watermark`, `denoise`, `color_grade`,
  `audio_trim`, `audio_speed`, `audio_volume`, `audio_fade`, `audio_normalize`,
  `visual_blur`, `visual_sharpen`, `visual_grayscale`, `visual_vignette`.

## Quick start

```bash
python -m pip install -r requirements.txt
copy .env.example .env
python main.py api
```

`python main.py api` now starts an embedded worker by default. Set `API_EMBEDDED_WORKER=false` when you want dedicated API and worker replicas, then run:

```bash
python main.py worker
```

Preflight the production schema/RPCs before rollout:

```bash
python main.py preflight-db
```

Run a local one-off pipeline without the queue:

```bash
python main.py run .\input.mp4 --config-file .\pipelines\examples\local_dubbing.json
```

Low-level operation pipeline example:

```bash
python main.py run .\input.mp4 --config-file .\pipelines\examples\low_level_basic.json
```

Canary smoke example (CI-friendly low-level flow):

```bash
python main.py run .\input.mp4 --config-file .\pipelines\examples\canary_smoke.json
```

Production-like API/worker smoke script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_prod.ps1 `
  -BaseUrl "https://your-api.example.com" `
  -ApiKey "your-api-secret" `
  -JobCount 4
```

Tips:
- Use `-DryRun` to print config without calling API.
- Omit `-InputVideoPath` to auto-generate a synthetic test video (requires `ffmpeg`).
- Script validates at least one cancelled running job and remaining jobs completed as `done`.

## Backends

- Local dev: `JOB_BACKEND=memory`, `ARTIFACT_STORE_BACKEND=local`
- Production: `JOB_BACKEND=supabase`, `ARTIFACT_STORE_BACKEND=supabase`

## Worker Polling

- `WORKER_POLL_MIN_SECONDS` (default `0.2`)
- `WORKER_POLL_MAX_SECONDS` (default `1.0`)
- `WORKER_POLL_BACKOFF_FACTOR` (default `1.5`)

Workers now back off polling when idle and reset to min interval when work is claimed or finished.
Benchmark notes and reproducible commands are in `benchmarks/README.md`.

## API

- `POST /jobs`: enqueue using `input_path`, `input_uri`, or an existing `source_key`
- `POST /jobs/upload`: upload a file directly into the shared artifact store and enqueue it
- `GET /jobs`: list recent jobs
- `GET /jobs/{job_id}`: fetch one job
- `GET /jobs/{job_id}/stream`: stream progress updates as Server-Sent Events
- `POST /jobs/{job_id}/cancel`: request cancellation
- `GET /admin`: minimal queue dashboard
- `GET /metrics`: Prometheus metrics endpoint when metrics dependencies are installed

### Auth

- API key auth is enabled by default with `API_AUTH_ENABLED=true`.
- Send key with either `x-api-key: <API_SECRET_KEY>` or `Authorization: Bearer <API_SECRET_KEY>`.
- `/health` is intentionally public for probes.
- CI gate for auth tests: set `REQUIRE_API_AUTH_TESTS=1` so missing FastAPI test stack fails the lane instead of skipping.
- `input_path` is disabled by default for API callers (`API_ALLOW_INPUT_PATH=false`) to avoid exposing host-local filesystem paths on public internet deployments.
- For public internet APIs, keep `API_ALLOW_CLIENT_SOURCE_SHA256=false` so clients cannot inject arbitrary cache identity hashes.
- Upload endpoint is size-limited by `API_UPLOAD_MAX_BYTES` (default `536870912` bytes).
- `API_RATE_LIMIT_PER_MINUTE` applies a per-key in-memory token bucket when auth is enabled.
- `API_ALLOWED_INPUT_URI_SCHEMES` restricts remote `input_uri` schemes before ffmpeg sees them.

## Additional Pipelines

- `subtitle` / `subtitle-only`: transcribe, translate, export subtitle output, and optionally hard-burn subtitles.
- `audio-extract` / `audio_extract`: extract and optionally loudness-normalize audio.
- `multilang-dubbing`: creates one child `dubbing` job per `payload.target_languages` entry.

Run the SQL in `supabase/schema.sql` against your Supabase Postgres instance before using the production backend.
The schema includes RPCs required by workers (`claim_jobs`, `release_stale_leases`, `request_cancel_job`) and a preflight verifier (`verify_jobs_schema_requirements`).

## Dubbing Payload Extensions

- `segment_strategy`: `chars` or `slot_adaptive` (default `slot_adaptive`)
- `segment_chars_per_second`: defaults to `14.0`
- `segment_retry_on_overflow`: defaults to `true`
- `segment_resplit_on_unresolved`: defaults to `true`
- `segment_max_resplit_parts`: defaults to `4`
- `cache_bust`: skips operation and step-cache reads for a fresh run.
- `tts_parallel_workers`: per-job override for parallel TTS segment generation.
- `background_music_url`, `background_music_volume`, `duck_during_speech`, `duck_level_db`: optional soundtrack mix controls.

Voice sync metadata now includes `voice_sync_overflow_segments`, `overflow_unresolved`, `segment_retry_applied`, and `segment_resplit_applied`.

Final remux now preserves original video duration by padding/trimming the mixed audio to match the input video length.

## TTS Engines

Set `TTS_ENGINE` to `edge-tts`, `openai`, or `google-cloud`.
OpenAI TTS uses `OPENAI_API_KEY` and `OPENAI_TTS_MODEL` (default `gpt-4o-mini-tts`).
Google Cloud REST TTS uses `GOOGLE_CLOUD_TTS_KEY`.

## Webhooks

Set `WEBHOOKS_ENABLED=true` to POST terminal job events to `metadata.webhook_url` or `payload.webhook_url`.
Webhook failures are logged and do not fail the job.
