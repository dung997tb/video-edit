# n8n Real Video Manual Test Harness

This harness prepares a visual, manual-UI n8n test run for Mewocamm Video Editor.
It does not require an n8n API key. n8n workflows are imported and run from the UI,
while a local collector records case events, verification results, summaries, and
ffprobe evidence.

## Prepare And Serve

```powershell
python scripts\run_n8n_real_video_manual.py --open-n8n
```

The command:

- creates `test_runs/n8n_real_video_<timestamp>/`
- generates five importable workflow JSON files under `workflows/`
- starts the Video API on `http://127.0.0.1:6666`
- starts the collector on `http://127.0.0.1:18799`
- writes `OPERATOR_GUIDE.md`, `run_manifest.json`, `cases.json`, `events.jsonl`, and summary files

Keep the command running while n8n workflows execute. Stop it with `Ctrl+C` after
the run so it writes final `summary.md`, `summary.html`, `summary.json`, and
`api_app_slice.log`.

## n8n UI Steps

1. Open n8n at `http://localhost:5678` and sign in.
2. Import each workflow listed in the generated `OPERATOR_GUIDE.md`.
3. Run `00 Smoke` first.
4. Run `01 Low-Level Matrix`, then `02 Pipeline AI Matrix`.
5. For `03 Webhook Batch`, activate the workflow before running its Manual Trigger branch.
6. Run `04 Negative Recovery`.

The smoke gate is enabled by default. If smoke has not passed, the other workflows
stop early and log `group_blocked`.

## Evidence

Each run directory contains:

- `events.jsonl`: raw event stream from n8n and collector verification
- `ffprobe/*.json`: media probe evidence for outputs
- `summary.md` and `summary.html`: human-readable results
- `summary.json`: machine-readable aggregate
- `api_stdout.log`: API process output when the harness starts the API
- `api_app_slice.log`: tail slice of `logs/app.log`
- `screenshots/`: place visual evidence captured from Chrome/Codex Browser

Secrets are masked in `run_manifest.json` and `OPERATOR_GUIDE.md`.

## Useful Options

```powershell
python scripts\run_n8n_real_video_manual.py --prepare-only
python scripts\run_n8n_real_video_manual.py --run-id my_run --collector-port 18800
python scripts\run_n8n_real_video_manual.py --n8n-public-url http://127.0.0.1:5678
python scripts\run_n8n_real_video_manual.py --no-smoke-gate
```
