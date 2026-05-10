from __future__ import annotations

from collections import defaultdict

from modules.base import BaseModule
from core.workflow.spec import NodeSpec, WorkflowSpec


def pipeline_to_workflow(modules: list[BaseModule]) -> WorkflowSpec:
    nodes: dict[str, NodeSpec] = {}
    previous_id: str | None = None
    seen: defaultdict[str, int] = defaultdict(int)
    for index, module in enumerate(modules, start=1):
        seen[module.NAME] += 1
        base_id = module.NAME if seen[module.NAME] == 1 else f"{module.NAME}_{seen[module.NAME]}"
        node_id = _safe_node_id(base_id) or f"node_{index:02d}"
        node = NodeSpec(
            id=node_id,
            type=f"compat.{module.NAME}",
            depends_on=[previous_id] if previous_id else [],
            params=dict(getattr(module, "params", {})),
            retry=1,
            module=module,
        )
        nodes[node_id] = node
        previous_id = node_id
    return WorkflowSpec(nodes=nodes, metadata={"source": "compat.pipeline"})


def _safe_node_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value.strip().lower())
