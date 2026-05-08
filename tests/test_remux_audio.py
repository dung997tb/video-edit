from __future__ import annotations

import unittest
from unittest.mock import patch

from core.context import PipelineContext
from core.file_manager import FileManager
from modules.video.remux_audio import RemuxAudioModule
from tests.helpers import make_services, make_test_root


class RemuxAudioModuleTests(unittest.TestCase):
    def test_remux_preserves_original_video_duration(self) -> None:
        root = make_test_root("remux-duration")
        services = make_services(root)
        file_manager = FileManager(root / "temp", root / "output", "job-remux")
        file_manager.ensure_dirs()
        context = PipelineContext(
            job_id="job-remux",
            pipeline_type="dubbing",
            input_video=str(root / "input.mp4"),
            source_sha256="source-hash",
            file_manager=file_manager,
            artifact_store=services.artifact_store,
            mixed_audio=str(root / "mixed.wav"),
        )
        module = RemuxAudioModule()

        with (
            patch.object(module, "_probe_duration", return_value=12.345),
            patch("modules.video.remux_audio.run_subprocess") as run_subprocess_mock,
        ):
            module.execute(context, services)

        command = run_subprocess_mock.call_args.args[0]
        self.assertIn("-filter_complex", command)
        filter_expr = command[command.index("-filter_complex") + 1]
        self.assertIn("apad", filter_expr)
        self.assertIn("atrim=duration=12.345", filter_expr)
        self.assertNotIn("-shortest", command)
        self.assertEqual(command[command.index("-map") + 1], "0:v:0")
        self.assertEqual(command[command.index("-map", command.index("-map") + 1) + 1], "[aout]")

    def test_remux_requires_audio_input(self) -> None:
        root = make_test_root("remux-no-audio")
        services = make_services(root)
        file_manager = FileManager(root / "temp", root / "output", "job-remux")
        file_manager.ensure_dirs()
        context = PipelineContext(
            job_id="job-remux",
            pipeline_type="dubbing",
            input_video=str(root / "input.mp4"),
            source_sha256="source-hash",
            file_manager=file_manager,
            artifact_store=services.artifact_store,
        )
        module = RemuxAudioModule()

        with self.assertRaises(ValueError):
            module.execute(context, services)
