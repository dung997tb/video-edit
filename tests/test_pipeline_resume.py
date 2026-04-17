from __future__ import annotations

import unittest
from pathlib import Path

from core.models import StepResult
from core.pipeline import PipelineRunner
from modules.base import BaseModule
from tests.helpers import make_services, make_test_root


class StepOne(BaseModule):
    NAME = "extract_audio"
    calls = 0

    def execute(self, context, services) -> StepResult:
        type(self).calls += 1
        output = context.file_manager.step_file("extract_audio")
        output.write_text("step-one", encoding="utf-8")
        return StepResult(
            context_patch={"audio_path": str(output)},
            artifacts={"audio_path": str(output)},
        )


class StepTwo(BaseModule):
    NAME = "transcript"
    calls = 0

    def execute(self, context, services) -> StepResult:
        type(self).calls += 1
        if type(self).calls == 1:
            raise RuntimeError("fail-once")
        output = context.file_manager.step_file("transcript")
        output.write_text("step-two", encoding="utf-8")
        return StepResult(
            context_patch={"transcript_path": str(output)},
            artifacts={"transcript_path": str(output)},
        )


def build_test_pipeline(job, services):
    return [StepOne(), StepTwo()]


class PipelineResumeTests(unittest.TestCase):
    def test_pipeline_resume_skips_completed_steps(self) -> None:
        root = make_test_root("pipeline-resume")
        services = make_services(root)
        StepOne.calls = 0
        StepTwo.calls = 0
        services.settings.step_retry_attempts = 1
        services.pipeline_builders["resume-test"] = build_test_pipeline
        input_video = root / "input.mp4"
        input_video.write_bytes(b"fake")
        job = services.job_manager.create_job(
            pipeline_type="resume-test",
            source_sha256="source-hash",
            input_path=str(input_video),
        )
        runner = PipelineRunner(services)

        with self.assertRaises(RuntimeError):
            runner.run_job(job)

        rerun_job = services.job_manager.get_job(job.id)
        self.assertIsNotNone(rerun_job)
        result = runner.run_job(rerun_job)

        self.assertEqual(StepOne.calls, 1)
        self.assertEqual(StepTwo.calls, 2)
        self.assertEqual(Path(result.audio_path).read_text(encoding="utf-8"), "step-one")
        self.assertEqual(Path(result.transcript_path).read_text(encoding="utf-8"), "step-two")
