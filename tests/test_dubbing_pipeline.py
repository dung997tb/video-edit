import unittest

from core.models import JobRecord
from modules.ai.dubbing import build_dubbing_pipeline
from tests.helpers import make_services, make_test_root


class DubbingPipelineTests(unittest.TestCase):
    def test_default_pipeline_includes_segmenter_and_retry_step(self) -> None:
        services = make_services(make_test_root("dubbing-pipeline-default"))
        job = JobRecord(
            id="job-default",
            pipeline_type="dubbing",
            source_sha256="source-hash",
            payload={},
        )

        names = [step.NAME for step in build_dubbing_pipeline(job, services)]

        self.assertIn("segmenter", names)
        self.assertIn("voice_sync_retry", names)

    def test_burn_subtitles_flag_inserts_burn_step_before_final(self) -> None:
        services = make_services(make_test_root("dubbing-pipeline"))
        job = JobRecord(
            id="job-1",
            pipeline_type="dubbing",
            source_sha256="source-hash",
            payload={"burn_subtitles": True},
        )

        names = [step.NAME for step in build_dubbing_pipeline(job, services)]

        self.assertEqual(names[-2:], ["burned_video", "final"])
