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

Run a local one-off pipeline without the queue:

```bash
python main.py run .\input.mp4 --config-file .\pipelines\examples\local_dubbing.json
```

Low-level operation pipeline example:

```bash
python main.py run .\input.mp4 --config-file .\pipelines\examples\low_level_basic.json
```

## Backends

- Local dev: `JOB_BACKEND=memory`, `ARTIFACT_STORE_BACKEND=local`
- Production: `JOB_BACKEND=supabase`, `ARTIFACT_STORE_BACKEND=supabase`

## API

- `POST /jobs`: enqueue using `input_path`, `input_uri`, or an existing `source_key`
- `POST /jobs/upload`: upload a file directly into the shared artifact store and enqueue it
- `GET /jobs`: list recent jobs
- `GET /jobs/{job_id}`: fetch one job
- `POST /jobs/{job_id}/cancel`: request cancellation

### Auth

- API key auth is enabled by default with `API_AUTH_ENABLED=true`.
- Send key with either `x-api-key: <API_SECRET_KEY>` or `Authorization: Bearer <API_SECRET_KEY>`.
- `/health` is intentionally public for probes.

Run the SQL in `supabase/schema.sql` against your Supabase Postgres instance before using the production backend.
The schema includes RPCs required by workers (`claim_jobs`, `release_stale_leases`, `request_cancel_job`).
