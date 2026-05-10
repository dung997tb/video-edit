from __future__ import annotations

from orchestrators.base import PipelineOrchestrator
from core.workflow import WorkflowSpec


class WorkflowOrchestrator(PipelineOrchestrator):
    NAME = "workflow"

    def build(self, job, services):
        payload = job.payload or {}
        workflow_payload = payload.get("workflow") or payload.get("workflow_spec")
        if not isinstance(workflow_payload, dict):
            raise ValueError("workflow pipeline requires payload.workflow as an object")
        return WorkflowSpec.from_dict(workflow_payload)
