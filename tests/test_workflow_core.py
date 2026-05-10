from __future__ import annotations

import unittest

from core.models import StepResult
from core.workflow import DAGRunner, NodeRegistry, NodeSpec, WorkflowSpec, pipeline_to_workflow
from modules.base import BaseModule


class _WorkflowStep(BaseModule):
    NAME = "workflow_step"

    def execute(self, context, services) -> StepResult:
        return StepResult(context_patch={"state": {self.params["key"]: True}})


class WorkflowCoreTests(unittest.TestCase):
    def test_pipeline_to_workflow_keeps_linear_dependencies(self) -> None:
        spec = pipeline_to_workflow([_WorkflowStep(params={"key": "a"}), _WorkflowStep(params={"key": "b"})])

        self.assertEqual(list(spec.nodes), ["workflow_step", "workflow_step_2"])
        self.assertEqual(spec.nodes["workflow_step_2"].depends_on, ["workflow_step"])

    def test_dag_runner_topological_batches(self) -> None:
        spec = WorkflowSpec(
            nodes={
                "a": NodeSpec(id="a", type="test.node"),
                "b": NodeSpec(id="b", type="test.node", depends_on=["a"]),
                "c": NodeSpec(id="c", type="test.node", depends_on=["a"]),
            }
        )

        batches = DAGRunner(spec, NodeRegistry()).topological_batches()

        self.assertEqual(batches[0], ["a"])
        self.assertEqual(set(batches[1]), {"b", "c"})

    def test_dag_runner_rejects_missing_dependency(self) -> None:
        spec = WorkflowSpec(nodes={"a": NodeSpec(id="a", type="test.node", depends_on=["missing"])})

        with self.assertRaises(ValueError):
            DAGRunner(spec, NodeRegistry()).topological_batches()

    def test_dag_runner_executes_nodes(self) -> None:
        spec = WorkflowSpec(nodes={"a": NodeSpec(id="a", type="test.node")})
        calls = []

        results = DAGRunner(spec, NodeRegistry()).run(
            execute_node=lambda node: calls.append(node.id) or StepResult(context_patch={"state": {"a": True}})
        )

        self.assertEqual(calls, ["a"])
        self.assertEqual(results["a"].status, "done")
