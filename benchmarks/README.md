# Benchmark Notes (2026-04-21)

## 1) Worker Poll Strategy

Command:

```bash
python benchmarks/worker_poll_benchmark.py --idle-seconds 300
```

Result snapshot:

```json
{
  "fixed_1_0": {
    "idle_polls": 300.0,
    "worst_case_new_job_latency_seconds": 1.0,
    "latency_after_recent_activity_seconds": 1.0
  },
  "fixed_0_5": {
    "idle_polls": 600.0,
    "worst_case_new_job_latency_seconds": 0.5,
    "latency_after_recent_activity_seconds": 0.5
  },
  "adaptive_0_2_to_1_0": {
    "idle_polls": 303.0,
    "worst_case_new_job_latency_seconds": 1.0,
    "latency_after_recent_activity_seconds": 0.2
  }
}
```

Decision:
- Keep adaptive polling defaults:
  - `WORKER_POLL_MIN_SECONDS=0.2`
  - `WORKER_POLL_MAX_SECONDS=1.0`
  - `WORKER_POLL_BACKOFF_FACTOR=1.5`
- Rationale: idle polling cost is close to fixed `1.0s`, but post-activity responsiveness is significantly better (`0.2s`).

## 2) ThreadPool vs ProcessPool

Command:

```bash
python -c "import json; from benchmarks.worker_pool_benchmark import run_benchmarks; print(json.dumps(run_benchmarks(workers=2,jobs=6,cpu_iterations=500000,subprocess_delay=0.05), ensure_ascii=False, indent=2))"
```

Result snapshot (current Windows sandbox):

```json
{
  "thread_pool": {
    "cpu_task": {
      "total_seconds": 0.289355400018394,
      "throughput_jobs_per_sec": 20.73574572867341
    },
    "subprocess_task": {
      "total_seconds": 0.25117830000817776,
      "throughput_jobs_per_sec": 23.887413840306486
    }
  },
  "process_pool": {
    "supported": false,
    "error": "PermissionError: [WinError 5] Access is denied"
  }
}
```

Decision:
- Runtime default remains `ThreadPoolExecutor(max_workers=N)`.
- Rationale: workload is primarily subprocess/I-O bound (ffmpeg), and ProcessPool is not reliably available in this environment. Re-evaluate in Linux production with unrestricted process sandboxing if needed.
