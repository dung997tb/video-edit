import unittest

from core.models import JobRecord
from modules.video.low_level import build_low_level_pipeline
from tests.helpers import make_services, make_test_root


class LowLevelPipelineTests(unittest.TestCase):
    def test_build_low_level_pipeline_with_known_operations(self) -> None:
        services = make_services(make_test_root("low-level-pipeline"))
        job = JobRecord(
            id="job-low-level",
            pipeline_type="low_level",
            source_sha256="source-hash",
            payload={
                "operations": [
                    {"name": "cut", "start": 0, "end": 5},
                    {"name": "speed", "factor": 1.2},
                    {"name": "flip", "mode": "horizontal"},
                    {"name": "audio_trim", "start": 0, "duration": 3},
                    {"name": "visual_blur", "luma_radius": 1.5},
                ]
            },
        )

        names = [step.NAME for step in build_low_level_pipeline(job, services)]

        self.assertEqual(names, ["cut", "speed", "flip", "audio_trim", "visual_blur", "export_low_level"])

    def test_build_low_level_pipeline_rejects_unknown_operation(self) -> None:
        services = make_services(make_test_root("low-level-pipeline-unknown"))
        job = JobRecord(
            id="job-low-level-invalid",
            pipeline_type="low_level",
            source_sha256="source-hash",
            payload={"operations": [{"name": "unknown_op"}]},
        )

        with self.assertRaises(ValueError):
            build_low_level_pipeline(job, services)

    def test_build_low_level_pipeline_accepts_structured_type_and_params(self) -> None:
        services = make_services(make_test_root("low-level-pipeline-structured"))
        job = JobRecord(
            id="job-low-level-structured",
            pipeline_type="low_level",
            source_sha256="source-hash",
            payload={
                "operations": [
                    {
                        "id": "crop-main",
                        "type": "crop",
                        "params": {"width": 320, "height": 240},
                    }
                ]
            },
        )

        steps = build_low_level_pipeline(job, services)

        self.assertEqual(steps[0].NAME, "crop")
        self.assertEqual(steps[0].params["width"], 320)
        self.assertEqual(steps[0].params["operation_id"], "crop-main")
