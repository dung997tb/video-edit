from __future__ import annotations

import unittest

from core.asset_graph_sqlite import SQLiteAssetGraph
from core.events_sqlite import SQLiteEventBus
from core.workflow.condition import evaluate_condition
from modules.video.low_level import VIDEO_OPERATION_MODULES
from orchestrators.factory import build_orchestrators
from tests.helpers import make_test_root


class SprintFeatureTests(unittest.TestCase):
    def test_new_low_level_operations_are_registered(self) -> None:
        for name in {
            "pad_border",
            "blur_bg_portrait",
            "loop",
            "filter_duration",
            "delogo",
            "audio_pitch",
            "content_variant",
            "hstack",
            "split_screen",
            "chromakey",
            "grid",
            "convert",
            "random_mirror",
            "auto_zoom",
        }:
            self.assertIn(name, VIDEO_OPERATION_MODULES)

    def test_new_pipeline_orchestrators_are_registered(self) -> None:
        orchestrators = build_orchestrators()

        self.assertIn("workflow", orchestrators)
        self.assertIn("semantic_edit", orchestrators)
        self.assertIn("silence_cut", orchestrators)
        self.assertIn("split_video", orchestrators)
        self.assertIn("extract_frames", orchestrators)

    def test_safe_condition_evaluator_handles_simple_expressions(self) -> None:
        context_vars = {"payload": {"lang": "vi", "count": 3}, "metadata": {}, "context": object()}

        self.assertTrue(evaluate_condition("payload['lang'] == 'vi'", context_vars))
        self.assertTrue(evaluate_condition("payload['count'] >= 2", context_vars))
        self.assertFalse(evaluate_condition("payload['count'] < 2", context_vars))

    def test_sqlite_asset_graph_persists_records(self) -> None:
        root = make_test_root("sqlite-asset-graph")
        graph = SQLiteAssetGraph(root / "asset_graph.db")
        graph.record(
            asset_id="asset-1",
            job_id="job-1",
            node_id="node-1",
            uri="out.mp4",
            kind="video",
            parents=["source"],
        )

        reloaded = SQLiteAssetGraph(root / "asset_graph.db")

        self.assertEqual(reloaded.get("asset-1").uri, "out.mp4")  # type: ignore[union-attr]
        self.assertEqual(reloaded.children_of("source")[0].asset_id, "asset-1")

    def test_sqlite_event_bus_persists_recent_events(self) -> None:
        root = make_test_root("sqlite-events")
        bus = SQLiteEventBus(root / "events.db")
        seen = []
        bus.subscribe("workflow.node.done", lambda event: seen.append(event.payload["node_id"]))

        bus.publish("workflow.node.done", {"node_id": "node-1"})
        reloaded = SQLiteEventBus(root / "events.db")

        self.assertEqual(seen, ["node-1"])
        self.assertEqual(reloaded.recent(event_type="workflow.node.done")[0].payload["node_id"], "node-1")
