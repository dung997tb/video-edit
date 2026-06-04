import unittest
from unittest.mock import patch

from core.context import PipelineContext
from core.file_manager import FileManager
from core.models import JobRecord
from modules.video.low_level import build_low_level_pipeline
from modules.video.split_video import SplitVideoModule
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

    def test_split_video_raises_when_no_segments_are_created(self) -> None:
        services = make_services(make_test_root("low-level-split-empty"))
        context = _pipeline_context(services, "job-split-empty")

        with patch("modules.video.split_video.run_ffmpeg", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "produced no segments"):
                SplitVideoModule(params={"segment_seconds": 1}).execute(context, services)

    def test_split_video_marks_low_level_finalize_to_skip_copy(self) -> None:
        services = make_services(make_test_root("low-level-split-result"))
        context = _pipeline_context(services, "job-split-result")

        def fake_ffmpeg(_context, _services, _command):
            output_path = context.file_manager.output("segments") / "segment_001.mp4"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"segment")

        with patch("modules.video.split_video.run_ffmpeg", side_effect=fake_ffmpeg):
            result = SplitVideoModule(params={"segment_seconds": 1}).execute(context, services)

        self.assertEqual(result.context_patch["state"]["skip_finalize"], True)
        self.assertEqual(len(result.artifacts["segments"]), 1)


def _pipeline_context(services, job_id: str) -> PipelineContext:
    file_manager = FileManager(
        temp_root=services.settings.temp_dir,
        output_root=services.settings.output_dir,
        job_id=job_id,
    )
    file_manager.ensure_dirs()
    input_video = file_manager.temp("input.mp4")
    input_video.write_bytes(b"video")
    return PipelineContext(
        job_id=job_id,
        pipeline_type="low_level",
        input_video=str(input_video),
        source_sha256="source",
        file_manager=file_manager,
        artifact_store=services.artifact_store,
    )
