from __future__ import annotations

import unittest

from core.context import PipelineContext
from core.file_manager import FileManager
from modules.ai.segmenter import SegmenterModule
from tests.helpers import make_services, make_test_root


def _build_context(name: str) -> tuple[PipelineContext, object]:
    root = make_test_root(name)
    services = make_services(root)
    file_manager = FileManager(root / "temp", root / "output", "job-segment")
    file_manager.ensure_dirs()
    context = PipelineContext(
        job_id="job-segment",
        pipeline_type="dubbing",
        input_video=str(root / "input.mp4"),
        source_sha256="source-hash",
        file_manager=file_manager,
        artifact_store=services.artifact_store,
    )
    return context, services


class SegmenterStrategyTests(unittest.TestCase):
    def test_chars_strategy_uses_max_chars(self) -> None:
        context, services = _build_context("segmenter-chars")
        context.translated_segments = [
            {
                "id": 1,
                "start": 0.0,
                "end": 2.0,
                "text": "mot hai ba bon nam sau bay tam chin muoi",
            }
        ]
        module = SegmenterModule(params={"strategy": "chars", "max_chars": 20})

        result = module.execute(context, services)

        self.assertGreater(len(result.context_patch["translated_segments"]), 1)

    def test_slot_adaptive_strategy_respects_slot_budget(self) -> None:
        context, services = _build_context("segmenter-slot-adaptive")
        context.translated_segments = [
            {
                "id": 1,
                "start": 0.0,
                "end": 0.5,
                "text": "xin chao day la doan van ban rat dai de test chia nho",
            }
        ]
        module = SegmenterModule(
            params={
                "strategy": "slot_adaptive",
                "max_chars": 80,
                "chars_per_second": 8.0,
            }
        )

        result = module.execute(context, services)
        chunks = result.context_patch["translated_segments"]

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all((item["end"] - item["start"]) >= 0 for item in chunks))

