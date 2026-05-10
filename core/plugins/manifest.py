from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PluginManifest:
    name: str
    version: str
    type: str
    entrypoint: str
    config_schema: dict[str, Any] = field(default_factory=dict)
    node_types: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginManifest":
        return cls(
            name=str(data["name"]),
            version=str(data.get("version", "0.0.0")),
            type=str(data["type"]),
            entrypoint=str(data["entrypoint"]),
            config_schema=dict(data.get("config_schema", {})),
            node_types=[str(item) for item in data.get("node_types", [])],
        )
