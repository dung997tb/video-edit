from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from core.cache import make_step_cache_key
from core.context import PipelineContext
from core.exceptions import JobCancelledError
from core.file_manager import FileManager
from core.models import JobRecord
from core.retry import execute_with_retry

if TYPE_CHECKING:
    from core.runtime import AppServices
    from modules.base import BaseModule


@dataclass(slots=True)
class LeaseHeartbeat:
    services: "AppServices"
    job_id: str
    worker_id: str
    stop_event: threading.Event

    def run(self) -> None:
        while not self.stop_event.wait(self.services.settings.heartbeat_interval_seconds):
            process = self.services.process_registry.get(self.job_id)
            pid = process.pid if process else None
            self.services.job_manager.heartbeat(
                self.job_id,
                self.worker_id,
                pid,
                self.services.settings.job_lease_seconds,
            )


class PipelineRunner:
    def __init__(self, services: "AppServices") -> None:
        self.services = services

    def run_job(self, job: JobRecord) -> PipelineContext:
        context = self._build_context(job)
        pipeline = self.services.pipeline_builders[job.pipeline_type](job, self.services)
        total_steps = len(pipeline)
        stop_event = threading.Event()
        heartbeat = LeaseHeartbeat(
            services=self.services,
            job_id=job.id,
            worker_id=self.services.settings.resolved_worker_id,
            stop_event=stop_event,
        )
        heartbeat_thread = threading.Thread(target=heartbeat.run, daemon=True)
        heartbeat_thread.start()
        try:
            self.services.job_manager.heartbeat(
                job.id,
                self.services.settings.resolved_worker_id,
                job.pid,
                self.services.settings.job_lease_seconds,
            )
            for index, step in enumerate(pipeline, start=1):
                self._raise_if_cancel_requested(job.id)
                progress = int(((index - 1) / total_steps) * 100) if total_steps else 0
                self.services.job_manager.update_progress(
                    job.id,
                    step_index=index - 1,
                    total_steps=total_steps,
                    current_step=step.NAME,
                    progress=progress,
                )
                step_hash = make_step_cache_key(
                    job.id,
                    step.NAME,
                    step.cache_inputs(context),
                    step.upstream_artifact_hashes(context),
                    self.services.settings.cache_version,
                )
                cached = self.services.cache_manager.load_step_result(job.id, step_hash, context.file_manager)
                if cached is not None:
                    context.update(cached.context_patch)
                    self.services.job_manager.update_progress(
                        job.id,
                        step_index=index,
                        total_steps=total_steps,
                        current_step=f"{step.NAME}:cached",
                        progress=int((index / total_steps) * 100),
                    )
                    continue

                result = execute_with_retry(
                    lambda: step.execute(context, self.services),
                    attempts=self.services.settings.step_retry_attempts,
                    delay_seconds=self.services.settings.step_retry_delay_seconds,
                )
                context.update(result.context_patch)
                self.services.cache_manager.save_step_result(job.id, step.NAME, step_hash, result, context.file_manager)
                self.services.job_manager.update_progress(
                    job.id,
                    step_index=index,
                    total_steps=total_steps,
                    current_step=step.NAME,
                    progress=int((index / total_steps) * 100),
                )

            self.services.job_manager.complete_job(job.id, context.output_video, metadata=context.metadata)
            return context
        except JobCancelledError as exc:
            self.services.job_manager.fail_job(job.id, str(exc), cancelled=True, metadata=context.metadata)
            raise
        except Exception as exc:
            self.services.job_manager.fail_job(job.id, str(exc), cancelled=False, metadata=context.metadata)
            raise
        finally:
            stop_event.set()
            heartbeat_thread.join(timeout=1)

    def _build_context(self, job: JobRecord) -> PipelineContext:
        file_manager = FileManager(
            temp_root=self.services.settings.temp_dir,
            output_root=self.services.settings.output_dir,
            job_id=job.id,
        )
        file_manager.ensure_dirs()
        input_video = self._resolve_input_video(job, file_manager)
        return PipelineContext(
            job_id=job.id,
            pipeline_type=job.pipeline_type,
            input_video=input_video,
            source_sha256=job.source_sha256,
            file_manager=file_manager,
            artifact_store=self.services.artifact_store,
            metadata=dict(job.metadata),
            state=dict(job.payload),
        )

    def _resolve_input_video(self, job: JobRecord, file_manager: FileManager) -> str:
        source_key = job.payload.get("source_key")
        if source_key:
            suffix = Path(source_key).suffix or ".mp4"
            destination = file_manager.temp(f"00_source_input{suffix}")
            self.services.artifact_store.download_file(source_key, destination)
            return str(destination)
        if job.input_path:
            local_path = Path(job.input_path)
            if not local_path.exists():
                raise FileNotFoundError(f"input_path not found: {job.input_path}")
            return str(local_path)
        if job.input_uri:
            return job.input_uri
        raise ValueError(f"job {job.id} is missing an input source")

    def _raise_if_cancel_requested(self, job_id: str) -> None:
        if self.services.job_manager.is_cancel_requested(job_id):
            raise JobCancelledError(f"job {job_id} cancelled by user")
