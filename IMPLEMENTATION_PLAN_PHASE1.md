# Phase 1 Stabilize - Implementation Plan

> Baseline: 53/58 n8n real-video tests PASS, 134 unit tests PASS.
> Target: 58/58 n8n tests PASS, zero zombie jobs, terminal callbacks reliable.

This plan intentionally keeps Phase 1 focused on correctness and reliability. Docker,
CI hardening, dashboards, and broader deploy work move to Phase 2 after the job
lifecycle is stable.

---

## Current Risk

The current repo appears partially migrated toward the Job State Contract:

- `core/job_manager.py` already imports `IllegalStateTransition`.
- `core/job_manager.py` already calls `record.status.is_terminal` and
  `record.status.can_transition_to(...)`.
- `core/models.py` does not yet define those `JobStatus` helpers.
- `core/exceptions.py` does not yet define `IllegalStateTransition`.

First checkpoint: make the core model/exception/job-manager contract internally
consistent before adding API, webhook, or Docker changes.

---

## Milestone 1 - Contract Core

Goal: every job status mutation follows a formal state machine, and every pipeline
exception reaches a terminal state.

### Files

- `core/models.py`
- `core/exceptions.py`
- `core/job_manager.py`
- `core/pipeline.py`
- `tests/test_job_state_contract.py`

### Changes

1. Add `JobStatus.is_terminal` and `JobStatus.can_transition_to(...)`.

```python
class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_JOB_STATUSES

    def can_transition_to(self, target: "JobStatus") -> bool:
        return target in JOB_STATUS_TRANSITIONS.get(self, frozenset())


TERMINAL_JOB_STATUSES = frozenset({
    JobStatus.DONE,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
})

JOB_STATUS_TRANSITIONS = {
    JobStatus.PENDING: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.RUNNING: frozenset({
        JobStatus.DONE,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.PENDING,  # restricted to release_stale_leases()
    }),
    JobStatus.DONE: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}
```

2. Add `IllegalStateTransition` to `core/exceptions.py`.

```python
class IllegalStateTransition(VideoEditError):
    """Raised when a job state transition violates the lifecycle contract."""
```

3. Tighten `InMemoryJobRepository`.

- `heartbeat()` must not resurrect terminal jobs.
- `update_progress()` must be a no-op for terminal jobs.
- `complete_job()` must require `status == RUNNING`.
- `fail_job()` must require `status == RUNNING`.
- `complete_job()` and `fail_job()` must check `worker_id` when supplied.
- `DONE` must set `progress = 100`.
- terminal states must clear `worker_id`, `lease_expires_at`, and `pid`.

Keep `worker_id` optional in the abstract interface only if existing tests or admin
code require it. Worker paths should always pass `worker_id`.

4. Fix stale leases and overlong jobs.

- `release_stale_leases(max_attempts=3)` is the only method allowed to do
  `RUNNING -> PENDING`.
- If `attempt_count >= max_attempts`, move to `FAILED`.
- If `cancel_requested` is true, move to `CANCELLED`.
- Add `fail_overlong_jobs(max_duration_seconds=3600)` as a separate method for
  alive-but-stuck jobs.

5. Fix `PipelineRunner.run_job()` build-phase boundary.

`_build_context()` and `_build_workflow()` must be inside `try/except`. The handler
must tolerate `context is None`.

```python
def run_job(self, job: JobRecord) -> PipelineContext:
    context = None
    active_step = None
    worker_id = self.services.settings.resolved_worker_id
    stop_event = threading.Event()
    heartbeat_thread = None
    try:
        context = self._build_context(job)
        workflow = self._build_workflow(job)
        # existing heartbeat + DAG execution
    except JobCancelledError as exc:
        self.services.job_manager.fail_job(
            job.id,
            str(exc),
            cancelled=True,
            error_detail=...,
            metadata=context.metadata if context is not None else job.metadata,
            worker_id=worker_id,
        )
        raise
    except Exception as exc:
        self.services.job_manager.fail_job(
            job.id,
            str(exc),
            error_detail=...,
            metadata=context.metadata if context is not None else job.metadata,
            worker_id=worker_id,
        )
        raise
    finally:
        stop_event.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1)
```

### Tests

Add focused unit tests first. Suggested minimum:

- pending -> running via claim
- pending -> cancelled via cancel
- running -> done via complete
- running -> failed via fail
- running -> cancelled via fail(cancelled=True)
- running -> pending via stale lease when attempts remain
- running -> failed via stale lease when max attempts reached
- done/failed/cancelled cannot transition again
- heartbeat does not resurrect terminal jobs
- terminal jobs ignore progress updates
- stale worker cannot complete or fail a job owned by another worker
- build-phase exception reaches `FAILED`

### Done

- `python -m pytest tests/test_job_state_contract.py -v` passes.
- Full unit test suite does not regress.

---

## Milestone 2 - Supabase Parity

Goal: Supabase behavior matches InMemory behavior.

### Files

- `core/job_manager.py`
- `supabase/schema.sql`
- any Supabase RPC definitions used by this repo
- `tests/test_supabase_repo.py`

### Changes

1. Apply the same guards to `SupabaseJobRepository`.

- `complete_job()` updates only rows with `status = 'running'`.
- `fail_job()` updates only rows with `status = 'running'`.
- `heartbeat()` updates only rows with matching `worker_id` and non-terminal status.
- `update_progress()` updates only non-terminal rows.

2. Update RPCs.

- `claim_jobs` must not claim cancelled or terminal rows.
- `release_stale_leases` must enforce `max_attempts`.
- `request_cancel_job` must be idempotent on terminal rows.

3. Add or confirm schema columns needed by later milestones.

Do not add webhook tracking fields here unless Milestone 4 is being implemented in
the same branch. Keep this milestone about lifecycle parity.

### Done

- InMemory and Supabase repository tests express the same state contract.
- Existing Supabase tests pass.

---

## Milestone 3 - Failure Taxonomy and API Validation

Goal: obvious invalid requests fail early, and unavoidable runtime failures produce
structured, retriable-aware errors.

### Files

- `core/models.py`
- `core/pipeline.py`
- `api/schemas.py`
- `api/routes/jobs.py`
- `tests/test_models.py`
- `tests/test_api_payload_integration.py`

### Changes

1. Extend `JobError`.

```python
@dataclass(slots=True)
class JobError:
    code: str
    message: str
    step: str | None = None
    retriable: bool = False
    stage: str | None = None
    operation: str | None = None
```

Add serialization round-trip support for the new fields.

2. Extend `JobErrorCode`.

- `UNKNOWN_OPERATION`
- `INVALID_PARAMS`
- `MAX_ATTEMPTS_EXCEEDED`
- `MAX_DURATION_EXCEEDED`
- `BUILD_WORKFLOW_FAILED`

3. Add low-level API validation.

Before creating a `low_level` job:

- reject empty `operations`
- reject missing operation name
- reject unsupported operation name
- reject known required-parameter omissions where simple to validate

Important: because `unknown_op` will now return HTTP 400 and create no job, webhook
failed-callback tests must use a different forced runtime failure or an internal
bypass path.

4. Enrich API responses with client actions.

Add additive fields to `JobResponse`:

- `is_terminal`
- `can_cancel`
- `can_retry`

Do not expose internal `allowed_transitions` to clients.

5. Optional in this milestone: retry clone endpoint.

`POST /jobs/{id}/retry` should create a new job from a failed retriable job. It must
not resurrect the old job. Store retry linkage in metadata, for example:

```python
metadata={
    **old.metadata,
    "retry_of": old.id,
    "retry_count": int(old.metadata.get("retry_count", 0)) + 1,
}
```

### Done

- `unknown_op` through public API returns HTTP 400 and creates no job.
- runtime/build failures still produce terminal failed jobs with structured errors.
- API responses expose client actions without exposing internal transitions.

---

## Milestone 4 - Webhook Delivery Guarantee

Goal: terminal callbacks are idempotent, observable, and retryable.

### Files

- `core/models.py`
- `core/job_manager.py`
- `supabase/schema.sql`
- `tests/test_webhook_dispatch.py`

### Schema / Model Fields

Add only when implementing this milestone:

```python
terminal_notified: bool = False
webhook_attempts: int = 0
last_webhook_error: str | None = None
```

### Repository Methods

Do not mutate a cloned record returned by `get_job()`. Add explicit repository
methods instead:

```python
def mark_webhook_attempt(
    self,
    job_id: str,
    *,
    success: bool,
    error: str | None = None,
) -> JobRecord | None: ...

def list_pending_webhooks(self, *, limit: int = 50) -> list[JobRecord]: ...
```

### Behavior

- `DONE` emits `job.completed`.
- `FAILED` emits `job.failed`.
- `CANCELLED` emits `job.cancelled`.
- Each terminal event should be marked delivered at most once.
- Failed delivery increments `webhook_attempts` and records `last_webhook_error`.
- `retry_pending_webhooks(max_retries=3)` retries undelivered terminal callbacks.
- Reapers and repeated terminal method calls must not resend already delivered events.

### Done

- done/failed/cancelled callbacks are sent exactly once on success.
- webhook delivery failure is recorded separately from job failure.
- pending webhook retry works and stops after max retries.

---

## Milestone 5 - n8n Custom Node Test Suite

Goal: verify the n8n community node package independently from the live n8n UI.

### Files

- `n8n-nodes-ai-video-engine/src/nodes/AiVideoEngine/AiVideoEngine.node.ts`
- `n8n-nodes-ai-video-engine/src/nodes/AiVideoEngineTrigger/AiVideoEngineTrigger.node.ts`
- `n8n-nodes-ai-video-engine/src/shared/helpers.ts`
- `n8n-nodes-ai-video-engine/test/*.test.ts`
- `n8n-nodes-ai-video-engine/examples/*.json`

### Required Test Coverage

The Vitest suite must cover:

- node package build with `npm run build`
- helper behavior: URL normalization, JSON parsing, payload merge, low-level
  operation templates, polling, output normalization
- `AI Video Engine` node description exposes the expected resources:
  - `job`
  - `preset`
- `job` operations are present:
  - `createCustom`
  - `uploadAndCreate`
  - `get`
  - `list`
  - `cancel`
  - `wait`
- `preset` operations are present:
  - `lowLevel`
  - `dubbing`
  - `subtitle`
  - `silenceCut`
  - `extractAudio`
  - `extractFrames`
- mocked API execution sends correct HTTP methods and paths:
  - `POST /jobs`
  - `POST /jobs/upload`
  - `GET /jobs/{id}`
  - `GET /jobs`
  - `POST /jobs/{id}/cancel`
- wait operation handles:
  - `done`
  - `failed`
  - `cancelled`
  - timeout
  - `failOnTerminalError = true/false`
- upload operation rejects missing binary input with a clear node error
- output mode `resultItems` explodes `metadata.result_items`
- trigger node accepts `job.completed`, `job.failed`, and `job.cancelled`
- trigger node ignores events not selected in the `events` parameter
- trigger node normalizes callback payload into `job_id`, `status`,
  `output_path`, `result_items`, `error`, and `error_detail`
- example workflows remain valid JSON and reference existing node names/types

### Commands

Run from `n8n-nodes-ai-video-engine`:

```powershell
npm test
npm run build
```

If lint is stable in the repo, also run:

```powershell
npm run lint
```

### Done

- n8n node Vitest suite passes.
- package build passes and emits dist assets.
- example workflow JSON files parse successfully.
- node tests cover both regular node and trigger node behavior.

---

## Milestone 6 - Full n8n Real-Video Connection Test

Goal: verify every n8n integration path against real video, using the packaged
custom nodes rather than ad-hoc HTTP nodes.

### Files

- `scripts/run_n8n_real_video_manual.py`
- `docs/N8N_REAL_VIDEO_MANUAL_TESTS.md`
- generated `test_runs/n8n_real_video_<timestamp>/`

### Required Coverage

The full run must verify these n8n connection paths:

- custom node package installed/loaded in n8n and workflows execute using the
  packaged nodes, not ad-hoc HTTP nodes
- n8n credential authentication to the Video API
- n8n submit-job node with JSON payload
- n8n upload/source-key flow with real video input
- n8n wait/poll flow until terminal status
- n8n webhook trigger flow for `job.completed`
- n8n webhook trigger flow for `job.failed`
- n8n webhook trigger flow for `job.cancelled`
- n8n batch workflow branch handling mixed success/failure/cancel results
- n8n negative cases: unsupported pipeline, missing input, invalid low-level
  operation
- output verification with `ffprobe` for every successful real-video output

### Test Groups

The harness should generate or document these workflow groups:

- `00 Smoke`: one short real-video low-level job, proves API and credentials work.
- `01 Low-Level Matrix`: all supported low-level video/audio/visual operations.
- `02 Pipeline AI Matrix`: all AI pipelines that can run with local/test providers.
- `03 Webhook Batch`: completed, failed, cancelled, and mixed batch branches.
- `04 Negative Recovery`: invalid input, cancel, timeout/reaper, and cleanup behavior.
- `05 Full Connection Verification`: one end-to-end workflow that touches
  credential auth, submit, poll, webhook callback, collector event logging, output
  verification, and summary generation in a single run.

### Evidence Requirements

Each full n8n run must write:

- `summary.md`
- `summary.html`
- `summary.json`
- `events.jsonl`
- `cases.json`
- `run_manifest.json`
- `api_stdout.log`
- `api_app_slice.log`
- `ffprobe/*.json` for successful output files
- optional screenshots under `screenshots/`

### Success Criteria

- All n8n connection paths above are covered by named cases.
- Every successful real-video case has an output path and ffprobe evidence.
- Failed/cancelled cases terminate correctly and emit the expected terminal callback.
- n8n workflows prove the custom `AI Video Engine` node and
  `AI Video Engine Trigger` node both work against the live API with real video.
- The final summary clearly reports total pass/fail count and failed case reasons.
- Target after Phase 1 fixes: `58/58 PASS` or higher if new full-connection cases
  increase the total count.

---

## Milestone 7 - n8n Evidence Rerun

Goal: prove Phase 1 fixed the real failing surface.

### Run

```powershell
python scripts\run_n8n_real_video_manual.py --open-n8n
```

### Expected

- `58/58` or higher n8n real-video tests PASS, depending on how many
  full-connection cases were added.
- `WB_CALLBACK_EVENTS` observes completed, failed, and cancelled callbacks.
- `WB_CALLBACK_FAILED_STUCK` no longer leaves a job stuck running at progress 0.
- Full connection verification confirms credential auth, submit, poll, webhook,
  collector, packaged custom nodes, and ffprobe evidence.
- Summary files are written under a new `test_runs/...` directory.

### Update

- Update the new run summary location in project notes.
- Keep failing evidence if any test remains red, with job id and callback logs.

---

## Deferred To Phase 2

These are useful, but should not block Phase 1 stabilization:

- `scripts/prod_smoke.py`
- `/health` and `/ready`
- Dockerfile
- `docker-compose.yml`
- GitHub Actions CI
- cleanup command
- monitoring dashboards

They become much easier after terminal state, retries, and webhook delivery are
reliable.

---

## Verification Checklist

Latest direct verification, 2026-05-12:

- `python -m pytest tests/ -v`: 153 passed.
- `cd n8n-nodes-ai-video-engine; npm test`: 3 files / 21 tests passed.
- `cd n8n-nodes-ai-video-engine; npm run build`: passed.
- `cd n8n-nodes-ai-video-engine; npm run lint`: passed.
- Direct API/lifecycle probe: 7 checks passed.
- Browser n8n retry evidence for `03 Webhook Batch`:
  `test_runs/n8n_real_video_browser_retry_20260512_091829/summary.md`
  shows 6 passed, 0 failed, and observed `job.completed`, `job.failed`, and
  `job.cancelled`.

- [x] `python -m pytest tests/test_job_state_contract.py -v`
- [x] `python -m pytest tests/test_models.py tests/test_job_manager.py -v`
- [x] `python -m pytest tests/test_api_payload_integration.py -v`
- [x] `python -m pytest tests/test_webhook_dispatch.py -v`
- [x] `python -m pytest tests/ -v`
- [x] `cd n8n-nodes-ai-video-engine; npm test`
- [x] `cd n8n-nodes-ai-video-engine; npm run build`
- [x] n8n node tests cover `AI Video Engine` job operations
- [x] n8n node tests cover preset operations
- [x] n8n trigger tests cover completed, failed, cancelled, and ignored events
- [x] example workflow JSON files parse and reference existing custom node types
- [ ] Full n8n connection test covers credential auth, submit, upload/source-key,
  polling, webhook trigger, batch, cancel, and negative flows
- [ ] live n8n full connection run uses the packaged custom nodes
- [ ] Every successful n8n real-video case has ffprobe evidence
- [x] `job.completed`, `job.failed`, and `job.cancelled` are all observed by the
  n8n webhook/collector path
- [ ] Full connection summary is saved under a new
  `test_runs/n8n_real_video_<timestamp>/` directory
- [ ] n8n real-video manual run reaches `58/58 PASS` or higher
- [x] Public `unknown_op` request returns HTTP 400 and creates no job
- [x] Internal/build failure creates `FAILED` job and emits `job.failed`
- [x] Cancel pending job becomes `CANCELLED` immediately
- [x] Cancel running job eventually becomes `CANCELLED`
- [x] Stale worker cannot complete/fail a re-claimed job
- [x] Repeated reaper runs do not mutate terminal jobs or resend delivered webhooks
