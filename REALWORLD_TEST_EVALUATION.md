# Real-World Test Evaluation

**AI Video Engine - Sprint 3 Real-World Validation**  
**Final run**: `20260509_232601`  
**Result**: `22 PASS / 0 FAIL / 5 BLOCKED`

## Summary

All automated runnable real-world tests passed. The only remaining blocked items are the n8n workflow scenarios, because workflow import/execution and production-domain validation are still manual in this local environment.

Final artifacts:

| Artifact | Path |
|---|---|
| Full raw log | `logs/realworld_test_20260509_232601.log` |
| Results JSON | `logs/realworld_test_20260509_232601.results.json` |
| Status JSON | `logs/realworld_test_20260509_232601.status.json` |
| Runner stdout mirror | `logs/realworld_test_20260509_232601.runner_stdout.log` |
| Runner stderr mirror | `logs/realworld_test_20260509_232601.runner_stderr.log` |

No `### ERROR SECTION START` markers and no `[ERROR]` result markers exist in the final full log.

## What Was Fixed

| Area | Fix |
|---|---|
| T1.6 Dubbing | Runner now uses `test.mp4`, which contains speech segments. `test_input.mp4` transcribed to `segments: []`, so it was not a valid dubbing input. |
| T2.4/T3.1 input_uri | Runner now serves the local MP4 through a temporary local HTTP static server instead of depending on `sample-videos.com`. |
| T2.6 Priority Queue | Runner now creates priority jobs concurrently and accepts same-worker-tick ties; it fails only if a lower-priority job starts before priority 10. |
| T5.3 Rate Limit | Runner now hits a protected endpoint (`/jobs/__rate_limit_probe__`) instead of `/health`, and uses a real-world runner limit of `200/min` so functional tests do not consume the limiter before the rate-limit test. |
| Port conflict | Runner now detects an already-responding base URL before starting its own API. Final run used `http://127.0.0.1:6667` because local `6666` was occupied by an external API process started with auth disabled. Product config/docs still default to `6666`. |

## Final Result Table

| Phase | Tests | Result |
|---|---:|---|
| Phase 1 - CLI | 7 | 7 PASS |
| Phase 2 - API Real Video | 7 | 7 PASS |
| Phase 3 - Webhook | 3 | 3 PASS |
| Phase 4 - n8n | 5 | 5 BLOCKED |
| Phase 5 - Stress | 5 | 5 PASS |

Key confirmations:

- Dubbing completed successfully and produced a final MP4 with audio/video.
- Upload, polling, SSE, local HTTP `input_uri`, cancellation, priority queue, and admin routes all passed.
- Webhooks passed for `job.completed`, `job.failed`, and `job.cancelled`.
- Rate limiting passed with `status_counts={404: 130, 429: 75}`.
- No automated test failed in the final run.

## Remaining Blocked Work

| Item | Status | Reason |
|---|---|---|
| W1-W4 n8n workflows | BLOCKED | n8n is reachable, but workflow import/execution is still manual. |
| W5 production n8n/domain validation | BLOCKED | Requires public domain or VPS reverse proxy validation. |

## Deployment Readiness

The API/video engine side is ready for VPS deployment validation. Before production handoff, complete the n8n workflow automation pass and run the same runner on the VPS target, preferably with `BASE_URL` pointing at the real HTTPS endpoint.

