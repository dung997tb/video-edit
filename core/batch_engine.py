from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from core.logger import logger
from core.pipeline import PipelineRunner


class WorkerService:
    def __init__(self, services: Any) -> None:
        self.services = services
        self.executor = ThreadPoolExecutor(max_workers=self.services.settings.max_workers)
        self.pipeline_runner = PipelineRunner(services)
        self._futures: dict[str, Future] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def run_forever(self) -> None:
        self._stop_event.clear()
        try:
            while not self._stop_event.is_set():
                try:
                    self.run_once()
                except Exception as exc:
                    logger.exception("worker loop iteration failed: {}", exc)
                self._stop_event.wait(self.services.settings.worker_poll_interval_seconds)
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

    def run_once(self) -> None:
        self.services.job_manager.release_stale_leases()
        self._collect_finished()
        available_slots = self.services.settings.max_workers - len(self._futures)
        if available_slots <= 0:
            return
        jobs = self.services.job_manager.claim_jobs(
            worker_id=self.services.settings.resolved_worker_id,
            limit=available_slots,
            lease_seconds=self.services.settings.job_lease_seconds,
        )
        for job in jobs:
            self._futures[job.id] = self.executor.submit(self.pipeline_runner.run_job, job)

    def _collect_finished(self) -> None:
        finished = [job_id for job_id, future in self._futures.items() if future.done()]
        for job_id in finished:
            future = self._futures.pop(job_id)
            try:
                future.result()
            except Exception as exc:
                logger.exception("job {} failed in worker loop: {}", job_id, exc)
