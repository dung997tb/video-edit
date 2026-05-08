from __future__ import annotations

import os
import shutil
import time
import unittest
from pathlib import Path

from core.batch_engine import WorkerService
from core.models import JobStatus, StepResult
from core.pipeline import PipelineRunner
from core.process import run_subprocess
from modules.base import BaseModule
from tests.helpers import make_services, make_test_root


def _probe_binary(command_name: str, env_var: str) -> str | None:
    candidate = shutil.which(command_name)
    if candidate:
        return candidate
    env_candidate = os.getenv(env_var)
    if env_candidate and Path(env_candidate).exists():
        return env_candidate
    try:
        from config import settings as app_settings
    except Exception:
        return None
    configured = getattr(app_settings, env_var.lower(), None)
    if configured and Path(str(configured)).exists():
        return str(configured)
    return None


FFMPEG_AVAILABLE = _probe_binary("ffmpeg", "FFMPEG_PATH") is not None and _probe_binary("ffprobe", "FFPROBE_PATH") is not None


class _LongFfmpegStep(BaseModule):
    NAME = "ffmpeg_long"

    def execute(self, context, services) -> StepResult:
        output_path = context.file_manager.temp("ffmpeg_long.wav")
        run_subprocess(
            [
                services.settings.ffmpeg_path,
                "-y",
                "-re",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=750:sample_rate=24000",
                "-t",
                "12",
                "-ac",
                "1",
                str(output_path),
            ],
            job_id=context.job_id,
            job_manager=services.job_manager,
            process_registry=services.process_registry,
            cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
            grace_seconds=services.settings.cancel_grace_seconds,
        )
        return StepResult(artifacts={"long_audio": str(output_path)})


class _FfmpegStepWithCounter(BaseModule):
    NAME = "ffmpeg_counter"
    calls = 0

    def execute(self, context, services) -> StepResult:
        type(self).calls += 1
        output_path = context.file_manager.temp("ffmpeg_counter.wav")
        run_subprocess(
            [
                services.settings.ffmpeg_path,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=24000:cl=mono",
                "-t",
                "0.2",
                str(output_path),
            ],
            job_id=context.job_id,
            job_manager=services.job_manager,
            process_registry=services.process_registry,
            cancel_check=lambda: services.job_manager.is_cancel_requested(context.job_id),
            grace_seconds=services.settings.cancel_grace_seconds,
        )
        return StepResult(
            context_patch={"audio_path": str(output_path)},
            artifacts={"audio_path": str(output_path)},
        )


class _FailOnceStep(BaseModule):
    NAME = "fail_once"
    has_failed = False

    def execute(self, context, services) -> StepResult:
        if not type(self).has_failed:
            type(self).has_failed = True
            raise RuntimeError("intentional failure")
        return StepResult(context_patch={"state": {"after_fail_once": True}})


class _FinalizeStep(BaseModule):
    NAME = "finalize_fake"

    def execute(self, context, services) -> StepResult:
        output_path = context.file_manager.step_file("final")
        output_path.write_text("ok", encoding="utf-8")
        return StepResult(
            context_patch={"output_video": str(output_path)},
            artifacts={"output_video": str(output_path)},
        )


@unittest.skipUnless(FFMPEG_AVAILABLE, "ffmpeg/ffprobe are required for integration tests")
class FfmpegIntegrationTests(unittest.TestCase):
    def test_cancel_mid_step_results_in_cancelled_job(self) -> None:
        root = make_test_root("ffmpeg-cancel")
        services = make_services(root)
        services.pipeline_builders["ffmpeg_cancel"] = lambda job, svc: [_LongFfmpegStep()]
        worker = WorkerService(services)
        try:
            input_path = root / "input.mp4"
            input_path.write_bytes(b"fake")
            job = services.job_manager.create_job(
                pipeline_type="ffmpeg_cancel",
                source_sha256="hash-cancel",
                input_path=str(input_path),
            )

            worker.run_once()
            deadline = time.time() + 3
            while time.time() < deadline:
                refreshed = services.job_manager.get_job(job.id)
                if refreshed and refreshed.pid:
                    break
                time.sleep(0.05)

            services.job_manager.request_cancel(job.id)

            deadline = time.time() + 5
            while time.time() < deadline:
                worker.run_once()
                refreshed = services.job_manager.get_job(job.id)
                if refreshed and refreshed.status in {JobStatus.CANCELLED, JobStatus.FAILED, JobStatus.DONE}:
                    break
                time.sleep(0.05)

            final = services.job_manager.get_job(job.id)
            self.assertIsNotNone(final)
            self.assertEqual(final.status, JobStatus.CANCELLED)
        finally:
            worker.executor.shutdown(wait=True, cancel_futures=False)

    def test_resume_uses_step_cache_after_failed_attempt(self) -> None:
        root = make_test_root("ffmpeg-resume")
        services = make_services(root)
        _FfmpegStepWithCounter.calls = 0
        _FailOnceStep.has_failed = False
        services.settings.step_retry_attempts = 1
        services.pipeline_builders["ffmpeg_resume"] = (
            lambda job, svc: [_FfmpegStepWithCounter(), _FailOnceStep(), _FinalizeStep()]
        )
        runner = PipelineRunner(services)

        input_path = root / "input.mp4"
        input_path.write_bytes(b"fake")
        job = services.job_manager.create_job(
            pipeline_type="ffmpeg_resume",
            source_sha256="hash-resume",
            input_path=str(input_path),
        )

        with self.assertRaises(RuntimeError):
            runner.run_job(job)
        self.assertEqual(_FfmpegStepWithCounter.calls, 1)

        refreshed = services.job_manager.get_job(job.id)
        self.assertIsNotNone(refreshed)
        context = runner.run_job(refreshed)

        self.assertEqual(_FfmpegStepWithCounter.calls, 1)
        self.assertTrue(bool(context.output_video))
