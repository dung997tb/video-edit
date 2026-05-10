import unittest

from core.result_manifest import build_result_items, merge_result_items
from tests.helpers import make_test_root


class ResultManifestTests(unittest.TestCase):
    def test_build_result_items_for_output_artifact(self) -> None:
        from core.file_manager import FileManager

        root = make_test_root("result-manifest-fm")
        manager = FileManager(root / "temp", root / "output", "job-1")
        output = manager.output("final.mp4")
        output.write_bytes(b"fake")

        items = build_result_items(
            job_id="job-1",
            node_id="final",
            step_name="final",
            artifacts={"output_video": str(output)},
            file_manager=manager,
            operation_id="op-final",
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["operation_id"], "op-final")
        self.assertEqual(items[0]["media_type"], "video")
        self.assertEqual(items[0]["artifact_scope"], "output")

    def test_merge_result_items_deduplicates_by_id(self) -> None:
        item = {"id": "one", "path": "a.mp4"}

        merged = merge_result_items([item], [item, {"id": "two", "path": "b.mp4"}])

        self.assertEqual([entry["id"] for entry in merged], ["one", "two"])


if __name__ == "__main__":
    unittest.main()
