from __future__ import annotations

import importlib
import json
from pathlib import Path

from core.plugins.manifest import PluginManifest
from core.workflow.registry import NodeRegistry


class PluginLoader:
    def __init__(self, plugin_root: str | Path = "plugins") -> None:
        self.plugin_root = Path(plugin_root)

    def discover(self) -> list[PluginManifest]:
        if not self.plugin_root.exists():
            return []
        manifests = []
        for path in self.plugin_root.rglob("plugin.json"):
            manifests.append(PluginManifest.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        return manifests

    def register_nodes(self, registry: NodeRegistry) -> list[PluginManifest]:
        loaded = []
        for manifest in self.discover():
            self._load_single(manifest, registry)
            loaded.append(manifest)
        return loaded

    def _load_single(self, manifest: PluginManifest, registry: NodeRegistry) -> None:
        target = _load_entrypoint(manifest.entrypoint)
        for node_type in manifest.node_types or [manifest.name]:
            registry.register(node_type, target)


def _load_entrypoint(entrypoint: str):
    module_name, _, attr = entrypoint.rpartition(".")
    if not module_name or not attr:
        raise ValueError(f"invalid plugin entrypoint: {entrypoint}")
    module = importlib.import_module(module_name)
    return getattr(module, attr)
