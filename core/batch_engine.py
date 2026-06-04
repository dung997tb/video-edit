from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from core.logger import logger
from core.metrics import metrics
from core.pipeline import PipelineRunner


class WorkerService:
    def __init__(self, services: Any) -> None:
        self.services = services
        self.executor = ThreadPoolExecutor(max_workers=self.services.settings.max_workers)
        self.pipeline_runner = PipelineRunner(services)
        default_interval = float(getattr(self.services.settings, "worker_poll_interval_seconds", 1.0))
        configured_min = float(getattr(self.services.settings, "worker_poll_min_seconds", default_interval))
        configured_max = float(getattr(self.services.settings, "worker_poll_max_seconds", default_interval))
        self._poll_min_seconds = max(0.01, configured_min)
        self._poll_max_seconds = max(self._poll_min_seconds, configured_max)
        self._poll_backoff_factor = max(
            1.0,
            float(getattr(self.services.settings, "worker_poll_backoff_factor", 1.5)),
        )
        self._current_poll_seconds = self._poll_min_seconds
        self._futures: dict[str, Future] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def run_forever(self) -> None:
        self._stop_event.clear()
        self._current_poll_seconds = self._poll_min_seconds
        try:
            while not self._stop_event.is_set():
                try:
                    activity = self.run_once()
                except Exception as exc:
                    logger.exception("worker loop iteration failed: {}", exc)
                    activity = False
                self._adjust_poll_interval(activity)
                self._stop_event.wait(self._current_poll_seconds)
        finally:
            self.executor.shutdown(wait=False, cancel_futures=False)

    def start_background(self, *, name: str = "worker-loop") -> threading.Thread:
        if self._thread and self._thread.is_alive():
            return self._thread
        self._thread = threading.Thread(target=self.run_forever, name=name, daemon=True)
        self._thread.start()
        return self._thread

    def stop(self, timeout: float | None = None) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=timeout)

    def run_once(self) -> bool:
        try:
            self.services.job_manager.release_stale_leases(
                max_attempts=int(getattr(self.services.settings, "max_job_attempts", 3)),
            )
        except TypeError:
            self.services.job_manager.release_stale_leases()
        fail_overlong = getattr(self.services.job_manager, "fail_overlong_jobs", None)
        if fail_overlong is not None:
            fail_overlong(max_duration_seconds=int(getattr(self.services.settings, "max_job_duration_seconds", 3600)))
        retry_webhooks = getattr(self.services.job_manager, "retry_pending_webhooks", None)
        if retry_webhooks is not None:
            retry_webhooks(max_retries=int(getattr(self.services.settings, "webhook_max_retries", 3)))
        had_finished = self._collect_finished()
        available_slots = self.services.settings.max_workers - len(self._futures)
        if metrics.enabled:
            metrics.active_jobs.set(len(self._futures))
        if available_slots <= 0:
            return had_finished
        jobs = self.services.job_manager.claim_jobs(
            worker_id=self.services.settings.resolved_worker_id,
            limit=available_slots,
            lease_seconds=self.services.settings.job_lease_seconds,
        )
        for job in jobs:
            self._futures[job.id] = self.executor.submit(self.pipeline_runner.run_job, job)
        if metrics.enabled:
            metrics.active_jobs.set(len(self._futures))
        return had_finished or bool(jobs)

    def _collect_finished(self) -> bool:
        finished = [job_id for job_id, future in self._futures.items() if future.done()]
        for job_id in finished:
            future = self._futures.pop(job_id)
            try:
                future.result()
            except Exception as exc:
                logger.exception("job {} failed in worker loop: {}", job_id, exc)
        if metrics.enabled:
            metrics.active_jobs.set(len(self._futures))
        return bool(finished)

    def _adjust_poll_interval(self, activity: bool) -> None:
        if activity:
            self._current_poll_seconds = self._poll_min_seconds
            return
        self._current_poll_seconds = min(
            self._poll_max_seconds,
            self._current_poll_seconds * self._poll_backoff_factor,
        )
