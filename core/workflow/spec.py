from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


NodeStatus = Literal["pending", "running", "done", "failed", "skipped"]


@dataclass(slots=True)
class NodeSpec:
    id: str
    type: str
    depends_on: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    retry: int = 1
    parallelism: int = 1
    condition: str | None = None
    input_map: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    isolated: bool = False
    module: Any | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("module", None)
        return payload

    @classmethod
    def from_dict(cls, node_id: str, data: dict[str, Any]) -> "NodeSpec":
        payload = dict(data)
        payload.setdefault("id", node_id)
        return cls(
            id=str(payload["id"]),
            type=str(payload["type"]),
            depends_on=[str(item) for item in payload.get("depends_on", [])],
            params=dict(payload.get("params", {})),
            retry=int(payload.get("retry", 1)),
            parallelism=max(1, int(payload.get("parallelism", 1))),
            condition=payload.get("condition"),
            input_map=dict(payload.get("inputs", payload.get("input_map", {}))),
            outputs=dict(payload.get("outputs", {})),
            isolated=bool(payload.get("isolated", False)),
        )


@dataclass(slots=True)
class WorkflowSpec:
    nodes: dict[str, NodeSpec]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": {node_id: node.to_dict() for node_id, node in self.nodes.items()},
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowSpec":
        nodes_payload = data.get("nodes", {})
        if not isinstance(nodes_payload, dict) or not nodes_payload:
            raise ValueError("workflow spec requires a non-empty nodes object")
        return cls(
            nodes={node_id: NodeSpec.from_dict(node_id, payload) for node_id, payload in nodes_payload.items()},
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(slots=True)
class NodeResult:
    node_id: str
    status: NodeStatus
    artifacts: dict[str, str | list[str]] = field(default_factory=dict)
    context_patch: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_code: str | None = None
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodeResult":
        return cls(
            node_id=str(data["node_id"]),
            status=data.get("status", "pending"),
            artifacts=dict(data.get("artifacts", {})),
            context_patch=dict(data.get("context_patch", {})),
            error=data.get("error"),
            error_code=data.get("error_code"),
            skipped_reason=data.get("skipped_reason"),
        )
