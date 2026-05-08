from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from typing import Any


def cpu_task(iterations: int) -> int:
    total = 0
    for index in range(iterations):
        total += (index * index) % 97
    return total


def subprocess_task(delay_seconds: float) -> int:
    command = [sys.executable, "-c", f"import time; time.sleep({delay_seconds}); print(1)"]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, shell=False)
    return int(completed.stdout.strip() or "0")


def _run_benchmark(executor: Executor, fn, *, jobs: int, arg) -> dict[str, float]:
    start = time.perf_counter()
    durations: list[float] = []
    futures = {}
    for _ in range(jobs):
        submitted_at = time.perf_counter()
        futures[executor.submit(fn, arg)] = submitted_at
    for future in as_completed(futures):
        future.result()
        durations.append(time.perf_counter() - futures[future])
    total = time.perf_counter() - start
    throughput = jobs / total if total > 0 else 0.0
    return {
        "jobs": float(jobs),
        "total_seconds": total,
        "throughput_jobs_per_sec": throughput,
        "p50_job_seconds": statistics.median(durations) if durations else 0.0,
        "p95_job_seconds": statistics.quantiles(durations, n=20)[-1] if len(durations) >= 2 else (durations[0] if durations else 0.0),
    }


def run_benchmarks(
    *,
    workers: int = 2,
    jobs: int = 8,
    cpu_iterations: int = 2_500_000,
    subprocess_delay: float = 0.25,
) -> dict[str, Any]:
    report: dict[str, Any] = {"thread_pool": {}, "process_pool": {}}
    with ThreadPoolExecutor(max_workers=workers) as thread_pool:
        report["thread_pool"]["cpu_task"] = _run_benchmark(
            thread_pool,
            cpu_task,
            jobs=jobs,
            arg=cpu_iterations,
        )
        report["thread_pool"]["subprocess_task"] = _run_benchmark(
            thread_pool,
            subprocess_task,
            jobs=jobs,
            arg=subprocess_delay,
        )

    try:
        with ProcessPoolExecutor(max_workers=workers) as process_pool:
            report["process_pool"]["cpu_task"] = _run_benchmark(
                process_pool,
                cpu_task,
                jobs=jobs,
                arg=cpu_iterations,
            )
            report["process_pool"]["subprocess_task"] = _run_benchmark(
                process_pool,
                subprocess_task,
                jobs=jobs,
                arg=subprocess_delay,
            )
    except Exception as exc:
        report["process_pool"] = {
            "supported": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    else:
        report["process_pool"]["supported"] = True
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare ThreadPool vs ProcessPool for worker workloads.")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--cpu-iterations", type=int, default=2_500_000)
    parser.add_argument("--subprocess-delay", type=float, default=0.25)
    args = parser.parse_args()

    report = run_benchmarks(
        workers=args.workers,
        jobs=args.jobs,
        cpu_iterations=args.cpu_iterations,
        subprocess_delay=args.subprocess_delay,
    )

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
