from __future__ import annotations

import unittest

from core.asset_graph import InMemoryAssetGraph
from core.events import InMemoryEventBus


class AssetEventTests(unittest.TestCase):
    def test_asset_graph_tracks_children(self) -> None:
        graph = InMemoryAssetGraph()
        graph.record(asset_id="child", job_id="job", node_id="node", uri="out.mp4", kind="video", parents=["source"])

        self.assertEqual(graph.children_of("source")[0].asset_id, "child")
        self.assertEqual(graph.list_for_job("job")[0].uri, "out.mp4")

    def test_event_bus_publishes_to_subscribers(self) -> None:
        bus = InMemoryEventBus()
        seen = []
        bus.subscribe("workflow.node.done", lambda event: seen.append(event.payload["node_id"]))

        bus.publish("workflow.node.done", {"node_id": "a"})

        self.assertEqual(seen, ["a"])
        self.assertEqual(bus.recent(event_type="workflow.node.done")[0].payload["node_id"], "a")
