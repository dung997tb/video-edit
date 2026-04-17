import unittest
from pathlib import Path

from core.file_manager import FileManager
from core.models import JobRecord
from core.pipeline import PipelineRunner
from tests.helpers import make_services, make_test_root


class PipelineInputTests(unittest.TestCase):
    def test_resolve_input_video_raises_when_input_path_missing(self) -> None:
        root = make_test_root("pipeline-input-missing")
        services = make_services(root)
        runner = PipelineRunner(services)
        file_manager = FileManager(services.settings.temp_dir, services.settings.output_dir, "job-missing")
        job = JobRecord(
            id="job-missing",
            pipeline_type="dubbing",
            source_sha256="hash",
            input_path=str(root / "not-found.mp4"),
        )

        with self.assertRaises(FileNotFoundError):
            runner._resolve_input_video(job, file_manager)  # noqa: SLF001

    def test_resolve_input_video_accepts_existing_input_path(self) -> None:
        root = make_test_root("pipeline-input-existing")
        input_path = root / "input.mp4"
        input_path.write_bytes(b"fake")
        services = make_services(root)
        runner = PipelineRunner(services)
        file_manager = FileManager(services.settings.temp_dir, services.settings.output_dir, "job-existing")
        job = JobRecord(
            id="job-existing",
            pipeline_type="dubbing",
            source_sha256="hash",
            input_path=str(input_path),
        )

        resolved = runner._resolve_input_video(job, file_manager)  # noqa: SLF001
        self.assertEqual(Path(resolved), input_path)

