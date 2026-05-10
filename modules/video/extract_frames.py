from __future__ import annotations

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import resolve_working_video, run_ffmpeg


@register
class ExtractFramesModule(BaseModule):
    NAME = "extract_frames"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services):
        interval = max(0.01, float(self.params.get("interval", self.params.get("interval_seconds", 1.0))))
        start = self.params.get("start")
        end = self.params.get("end")
        duration = self.params.get("duration")
        count = self.params.get("count")
        output_dir = context.file_manager.output("frames")
        output_dir.mkdir(parents=True, exist_ok=True)
        pattern = output_dir / "frame_%05d.jpg"
        command = [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            resolve_working_video(context),
        ]
        if start is not None:
            command.extend(["-ss", f"{float(start):.3f}"])
        resolved_duration = None
        if end is not None and start is not None:
            resolved_duration = max(float(end) - float(start), 0.001)
            command.extend(["-t", f"{resolved_duration:.3f}"])
        elif duration is not None:
            resolved_duration = max(float(duration), 0.001)
            command.extend(["-t", f"{resolved_duration:.3f}"])
        elif end is not None:
            command.extend(["-to", f"{float(end):.3f}"])
        fps_filter = f"fps=1/{interval:.6f}"
        if count is not None and resolved_duration:
            fps_filter = f"fps={max(int(count), 1) / resolved_duration:.6f}"
        command.extend(
            [
                "-vf",
                fps_filter,
                "-q:v",
                str(self.params.get("quality", 2)),
            ]
        )
        if count is not None:
            command.extend(["-frames:v", str(max(int(count), 1))])
        command.append(str(pattern))
        run_ffmpeg(
            context,
            services,
            command,
        )
        outputs = [str(path) for path in sorted(output_dir.glob("frame_*.jpg"))]
        return StepResult(
            context_patch={
                "output_video": str(output_dir),
                "metadata": {"frames": outputs},
            },
            artifacts={"frames": outputs},
        )
