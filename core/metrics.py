from __future__ import annotations

from typing import Any


class Metrics:
    def __init__(self) -> None:
        self.enabled = False
        self.job_submitted_total: Any = None
        self.job_terminal_total: Any = None
        self.job_duration_seconds: Any = None
        self.active_jobs: Any = None
        try:
            from prometheus_client import Counter, Gauge, Histogram
        except ImportError:
            return
        self.enabled = True
        self.job_submitted_total = Counter("job_submitted_total", "Total jobs submitted", ["pipeline_type"])
        self.job_terminal_total = Counter("job_terminal_total", "Jobs reaching terminal state", ["pipeline_type", "status"])
        self.job_duration_seconds = Histogram(
            "job_duration_seconds",
            "Job processing duration",
            ["pipeline_type", "status"],
        )
        self.active_jobs = Gauge("active_jobs", "Currently running jobs")

    def submitted(self, pipeline_type: str) -> None:
        if self.enabled:
            self.job_submitted_total.labels(pipeline_type=pipeline_type).inc()

    def terminal(self, pipeline_type: str, status: str, duration_seconds: float | None) -> None:
        if not self.enabled:
            return
        self.job_terminal_total.labels(pipeline_type=pipeline_type, status=status).inc()
        if duration_seconds is not None:
            self.job_duration_seconds.labels(pipeline_type=pipeline_type, status=status).observe(duration_seconds)


metrics = Metrics()
