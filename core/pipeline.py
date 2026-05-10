from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from core.cache import make_step_cache_key
from core.context import PipelineContext
from core.exceptions import JobCancelledError, WorkflowNodeError
from core.file_manager import FileManager
from core.models import JobError, JobErrorCode, JobRecord
from core.process import SubprocessExecutionError
from core.result_manifest import build_result_items, merge_result_items
from core.retry import execute_with_retry
from core.workflow import DAGRunner, WorkflowSpec, build_default_registry, pipeline_to_workflow
from core.workflow.condition import evaluate_condition
from core.workflow.spec import NodeResult, NodeSpec

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
        workflow = self._build_workflow(job)
        total_steps = len(workflow.nodes)
        worker_id = self.services.settings.resolved_worker_id
        active_step = None
        stop_event = threading.Event()
        heartbeat = LeaseHeartbeat(
            services=self.services,
            job_id=job.id,
            worker_id=worker_id,
            stop_event=stop_event,
        )
        heartbeat_thread = threading.Thread(target=heartbeat.run, daemon=True)
        heartbeat_thread.start()
        try:
            self.services.job_manager.heartbeat(
                job.id,
                worker_id,
                job.pid,
                self.services.settings.job_lease_seconds,
            )
            registry = build_default_registry()
            results: dict[str, NodeResult] = {}

            def on_node_start(node: NodeSpec, completed_count: int, node_total: int) -> None:
                nonlocal active_step
                module = registry.build(node)
                active_step = getattr(module, "NAME", node.id)
                progress = int((completed_count / node_total) * 100) if node_total else 0
                self._raise_if_cancel_requested(job.id)
                self.services.job_manager.update_progress(
                    job.id,
                    worker_id=worker_id,
                    step_index=completed_count,
                    total_steps=node_total,
                    current_step=active_step,
                    progress=progress,
                )

            def execute_node(node: NodeSpec):
                module = registry.build(node)
                return self._execute_workflow_node(node, module, context)

            def on_node_result(node: NodeSpec, result: NodeResult) -> None:
                results[node.id] = result
                if result.status == "done":
                    context.update(result.context_patch)
                self._save_workflow_state(job.id, workflow, results)
                done_count = len([item for item in results.values() if item.status in {"done", "skipped"}])
                current_step = node.id if result.status != "done" else getattr(registry.build(node), "NAME", node.id)
                self.services.job_manager.update_progress(
                    job.id,
                    worker_id=worker_id,
                    step_index=done_count,
                    total_steps=total_steps,
                    current_step=current_step,
                    progress=int((done_count / total_steps) * 100) if total_steps else 100,
                )

            DAGRunner(workflow, registry).run(
                execute_node=execute_node,
                should_skip=lambda node: self._should_skip_node(node, context),
                on_node_start=on_node_start,
                on_node_result=on_node_result,
            )

            self.services.job_manager.complete_job(
                job.id,
                context.output_video,
                metadata=context.metadata,
                worker_id=worker_id,
            )
            return context
        except JobCancelledError as exc:
            self.services.job_manager.fail_job(
                job.id,
                str(exc),
                cancelled=True,
                error_detail=JobError(
                    code=JobErrorCode.CANCELLED.value,
                    message=str(exc),
                    step=active_step,
                    retriable=False,
                ),
                metadata=context.metadata,
                worker_id=worker_id,
            )
            raise
        except Exception as exc:
            self.services.job_manager.fail_job(
                job.id,
                str(exc),
                cancelled=False,
                error_detail=self._build_error_detail(exc, active_step),
                metadata=context.metadata,
                worker_id=worker_id,
            )
            raise
        finally:
            stop_event.set()
            heartbeat_thread.join(timeout=1)

    def _build_workflow(self, job: JobRecord) -> WorkflowSpec:
        built = self.services.pipeline_builders[job.pipeline_type](job, self.services)
        if isinstance(built, WorkflowSpec):
            return built
        return pipeline_to_workflow(built)

    def _build_context(self, job: JobRecord) -> PipelineContext:
        output_name = job.payload.get("output_name")
        file_manager = FileManager(
            temp_root=self.services.settings.temp_dir,
            output_root=self.services.settings.output_dir,
            job_id=job.id,
            output_name=output_name,
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

    def _cache_bust_enabled(self, context: PipelineContext) -> bool:
        return bool(context.state.get("cache_bust") or context.state.get("bypass_cache"))

    def _should_skip_node(self, node: NodeSpec, context: PipelineContext) -> tuple[bool, str | None]:
        if not node.condition:
            return False, None
        try:
            allowed_locals = {"payload": context.state, "metadata": context.metadata, "context": context}
            return (not evaluate_condition(node.condition, allowed_locals), "condition evaluated false")
        except Exception as exc:
            raise ValueError(f"invalid condition for workflow node {node.id}: {exc}") from exc

    def _execute_workflow_node(self, node: NodeSpec, step: "BaseModule", context: PipelineContext):
        step_name = getattr(step, "NAME", node.id)
        step_hash = make_step_cache_key(
            context.job_id,
            node.id,
            step.cache_inputs(context),
            step.upstream_artifact_hashes(context),
            self.services.settings.cache_version,
        )
        cached = None
        if not self._cache_bust_enabled(context):
            cached = self.services.cache_manager.load_step_result(context.job_id, step_hash, context.file_manager)
        if cached is not None:
            result = cached_to_step_result(cached.context_patch, cached.artifacts, cached.metadata, context.file_manager)
            context.update(result.context_patch)
            self._merge_step_result_metadata(step_name, node, result, context)
            return result

        result = self._run_step_with_observability(step, context, attempts=max(node.retry, 1))
        context.update(result.context_patch)
        self._merge_step_result_metadata(step_name, node, result, context)
        self.services.cache_manager.save_step_result(context.job_id, step_name, step_hash, result, context.file_manager)
        self._record_assets(node, result, context)
        self._publish_event("workflow.node.done", {"job_id": context.job_id, "node_id": node.id, "step": step_name})
        return result

    def _run_step_with_observability(self, step: "BaseModule", context: PipelineContext, *, attempts: int | None = None):
        attempts = attempts or self.services.settings.step_retry_attempts
        tracing_enabled = bool(getattr(self.services.settings, "tracing_enabled", False))
        if not tracing_enabled:
            return execute_with_retry(
                lambda s=step, c=context: s.execute(c, self.services),
                attempts=attempts,
                delay_seconds=self.services.settings.step_retry_delay_seconds,
            )
        try:
            from opentelemetry import trace
        except ImportError:
            return execute_with_retry(
                lambda s=step, c=context: s.execute(c, self.services),
                attempts=attempts,
                delay_seconds=self.services.settings.step_retry_delay_seconds,
            )
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span(f"pipeline.step.{step.NAME}") as span:
            span.set_attribute("job.id", context.job_id)
            span.set_attribute("step.name", step.NAME)
            return execute_with_retry(
                lambda s=step, c=context: s.execute(c, self.services),
                attempts=attempts,
                delay_seconds=self.services.settings.step_retry_delay_seconds,
            )

    def _save_workflow_state(self, job_id: str, workflow: WorkflowSpec, results: dict[str, NodeResult]) -> None:
        payload = {
            "workflow": workflow.to_dict(),
            "results": {node_id: result.to_dict() for node_id, result in results.items()},
        }
        try:
            self.services.artifact_store.upload_json(f"jobs/{job_id}/workflow/results.json", payload)
        except Exception:
            pass

    def _record_assets(self, node: NodeSpec, result, context: PipelineContext) -> None:
        graph = getattr(self.services, "asset_graph", None)
        if graph is None:
            return
        for name, path_or_paths in result.artifacts.items():
            paths = path_or_paths if isinstance(path_or_paths, list) else [path_or_paths]
            for path in paths:
                graph.record(
                    asset_id=f"{context.job_id}:{node.id}:{name}:{path}",
                    job_id=context.job_id,
                    node_id=node.id,
                    uri=str(path),
                    kind=name,
                    parents=[context.source_sha256],
                )

    def _merge_step_result_metadata(self, step_name: str, node: NodeSpec, result, context: PipelineContext) -> None:
        if result.metadata:
            context.update({"metadata": result.metadata})
        additions = build_result_items(
            job_id=context.job_id,
            node_id=node.id,
            step_name=step_name,
            artifacts=dict(result.artifacts),
            file_manager=context.file_manager,
            operation_id=node.params.get("operation_id") or node.params.get("id"),
            metadata=result.metadata,
        )
        if additions:
            context.metadata["result_items"] = merge_result_items(context.metadata.get("result_items"), additions)

    def _publish_event(self, event_type: str, payload: dict[str, Any]) -> None:
        event_bus = getattr(self.services, "event_bus", None)
        if event_bus is not None:
            event_bus.publish(event_type, payload)

    def _build_error_detail(self, exc: Exception, step_name: str | None) -> JobError:
        code = JobErrorCode.UNKNOWN.value
        if isinstance(exc, WorkflowNodeError):
            code = exc.error_code or code
            step_name = exc.node_id
        if code == JobErrorCode.UNKNOWN.value:
            if isinstance(exc, FileNotFoundError):
                code = JobErrorCode.INPUT_NOT_FOUND.value
            elif isinstance(exc, SubprocessExecutionError):
                code = JobErrorCode.FFMPEG_FAILED.value
            elif step_name == "transcript":
                code = JobErrorCode.TRANSCRIPTION_FAILED.value
            elif step_name == "translate":
                code = JobErrorCode.TRANSLATION_FAILED.value
            elif step_name == "tts":
                code = JobErrorCode.TTS_FAILED.value
            elif step_name in {"synced_audio", "voice_sync_retry"}:
                code = JobErrorCode.VOICE_SYNC_FAILED.value
        return JobError(
            code=code,
            message=str(exc),
            step=step_name,
            retriable=not isinstance(exc, (FileNotFoundError, ValueError)),
        )


def cached_to_step_result(context_patch, artifacts, metadata=None, file_manager=None):
    from core.models import StepResult

    artifact_payload = {}
    for item in artifacts:
        artifact_payload[item.relative_path] = (
            str(file_manager.resolve_artifact_path(item.kind, item.relative_path)) if file_manager is not None else item.cache_key
        )
    return StepResult(
        context_patch=dict(context_patch),
        artifacts=artifact_payload,
        metadata=dict(metadata or {}),
    )
