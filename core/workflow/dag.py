from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable

from core.exceptions import WorkflowNodeError
from core.models import StepResult
from core.exceptions import JobCancelledError
from core.models import JobErrorCode
from core.process import SubprocessExecutionError
from core.workflow.registry import NodeRegistry
from core.workflow.spec import NodeResult, NodeSpec, WorkflowSpec


ExecuteNode = Callable[[NodeSpec], StepResult]
NodeCallback = Callable[[NodeSpec, int, int], None]
ResultCallback = Callable[[NodeSpec, NodeResult], None]


class DAGRunner:
    def __init__(self, spec: WorkflowSpec, registry: NodeRegistry) -> None:
        self.spec = spec
        self.registry = registry

    def run(
        self,
        *,
        execute_node: ExecuteNode,
        should_skip: Callable[[NodeSpec], tuple[bool, str | None]] | None = None,
        on_node_start: NodeCallback | None = None,
        on_node_result: ResultCallback | None = None,
    ) -> dict[str, NodeResult]:
        batches = self.topological_batches()
        results: dict[str, NodeResult] = {}
        completed_count = 0
        total = len(self.spec.nodes)
        for batch in batches:
            runnable = []
            for node_id in batch:
                node = self.spec.nodes[node_id]
                skip, reason = should_skip(node) if should_skip else (False, None)
                if skip:
                    completed_count += 1
                    result = NodeResult(node_id=node.id, status="skipped", skipped_reason=reason)
                    results[node.id] = result
                    if on_node_result:
                        on_node_result(node, result)
                    continue
                runnable.append(node)

            if self._can_run_parallel(runnable):
                batch_results = self._run_parallel(
                    runnable,
                    execute_node=execute_node,
                    on_node_start=on_node_start,
                    completed_count=completed_count,
                    total=total,
                )
                for node, result in batch_results:
                    completed_count += 1
                    results[node.id] = result
                    if on_node_result:
                        on_node_result(node, result)
                    if result.status == "failed":
                        raise WorkflowNodeError(
                            node.id,
                            result.error or f"workflow node failed: {node.id}",
                            result.error_code,
                        )
            else:
                for node in runnable:
                    if on_node_start:
                        on_node_start(node, completed_count, total)
                    result = self._execute(node, execute_node)
                    completed_count += 1
                    results[node.id] = result
                    if on_node_result:
                        on_node_result(node, result)
                    if result.status == "failed":
                        raise WorkflowNodeError(
                            node.id,
                            result.error or f"workflow node failed: {node.id}",
                            result.error_code,
                        )
        return results

    def topological_batches(self) -> list[list[str]]:
        self._validate()
        incoming = {node_id: set(node.depends_on) for node_id, node in self.spec.nodes.items()}
        ready = sorted(node_id for node_id, deps in incoming.items() if not deps)
        batches: list[list[str]] = []
        while ready:
            batch = ready
            batches.append(batch)
            ready = []
            for node_id in batch:
                for candidate, deps in incoming.items():
                    deps.discard(node_id)
                    if not deps and candidate not in {item for group in batches for item in group} and candidate not in ready:
                        ready.append(candidate)
            ready.sort()
        scheduled = {node_id for batch in batches for node_id in batch}
        if scheduled != set(self.spec.nodes):
            unresolved = ", ".join(sorted(set(self.spec.nodes) - scheduled))
            raise ValueError(f"workflow contains a dependency cycle: {unresolved}")
        return batches

    def _validate(self) -> None:
        for node in self.spec.nodes.values():
            for dependency in node.depends_on:
                if dependency not in self.spec.nodes:
                    raise ValueError(f"node '{node.id}' depends on missing node '{dependency}'")

    def _can_run_parallel(self, nodes: list[NodeSpec]) -> bool:
        return len(nodes) > 1 and all(node.isolated for node in nodes)

    def _run_parallel(
        self,
        nodes: list[NodeSpec],
        *,
        execute_node: ExecuteNode,
        on_node_start: NodeCallback | None,
        completed_count: int,
        total: int,
    ) -> list[tuple[NodeSpec, NodeResult]]:
        results: list[tuple[NodeSpec, NodeResult]] = []
        with ThreadPoolExecutor(max_workers=max(node.parallelism for node in nodes)) as executor:
            futures = {}
            for offset, node in enumerate(nodes):
                if on_node_start:
                    on_node_start(node, completed_count + offset, total)
                futures[executor.submit(self._execute, node, execute_node)] = node
            for future in as_completed(futures):
                node = futures[future]
                results.append((node, future.result()))
        return results

    def _execute(self, node: NodeSpec, execute_node: ExecuteNode) -> NodeResult:
        try:
            step_result = execute_node(node)
            return NodeResult(
                node_id=node.id,
                status="done",
                artifacts=dict(step_result.artifacts),
                context_patch=dict(step_result.context_patch),
            )
        except Exception as exc:
            if isinstance(exc, JobCancelledError):
                raise
            return NodeResult(
                node_id=node.id,
                status="failed",
                error=str(exc),
                error_code=_error_code_for_exception(exc),
            )


def _error_code_for_exception(exc: Exception) -> str | None:
    if isinstance(exc, SubprocessExecutionError):
        return JobErrorCode.FFMPEG_FAILED.value
    if isinstance(exc, FileNotFoundError):
        return JobErrorCode.INPUT_NOT_FOUND.value
    return None
