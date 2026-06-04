from __future__ import annotations

from pathlib import Path

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import resolve_working_video, run_ffmpeg


@register
class SplitVideoModule(BaseModule):
    NAME = "split_video"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services):
        start = self.params.get("start")
        end = self.params.get("end")
        count = self.params.get("count")
        total_duration = self.params.get("total_duration")
        if total_duration is None and (start is not None or end is not None or count is not None):
            total_duration = self.params.get("duration")
        segment_default = self.params.get("segment_duration", self.params.get("duration", 10))
        segment_seconds = max(0.1, float(self.params.get("segment_seconds", segment_default)))
        output_dir = context.file_manager.output("segments")
        output_dir.mkdir(parents=True, exist_ok=True)
        custom_segments = self.params.get("segments")
        if custom_segments:
            if not isinstance(custom_segments, list):
                raise ValueError("split_video segments must be a list")
            outputs = []
            for index, segment in enumerate(custom_segments, start=1):
                if not isinstance(segment, dict):
                    raise ValueError("split_video segment items must be objects")
                start = float(segment.get("start", 0))
                end = segment.get("end")
                duration = segment.get("duration")
                if end is not None:
                    duration = max(float(end) - start, 0.001)
                if duration is None:
                    raise ValueError("split_video custom segments require end or duration")
                output_path = output_dir / f"segment_{index:03d}.mp4"
                run_ffmpeg(
                    context,
                    services,
                    [
                        services.settings.ffmpeg_path,
                        "-y",
                        "-i",
                        resolve_working_video(context),
                        "-ss",
                        f"{start:.3f}",
                        "-t",
                        f"{float(duration):.3f}",
                        "-map",
                        "0:v:0",
                        "-map",
                        "0:a?",
                        "-c:v",
                        str(self.params.get("video_codec", "libx264")),
                        "-preset",
                        str(self.params.get("preset", "veryfast")),
                        "-crf",
                        str(self.params.get("crf", 23)),
                        "-c:a",
                        str(self.params.get("audio_codec", "aac")),
                        "-movflags",
                        "+faststart",
                        "-reset_timestamps",
                        "1",
                        str(output_path),
                    ],
                )
                outputs.append(str(output_path))
            return _segments_result(output_dir, outputs)

        pattern = output_dir / "segment_%03d.mp4"
        command = [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            resolve_working_video(context),
        ]
        if start is not None:
            command.extend(["-ss", f"{float(start):.3f}"])
        if end is not None and start is not None:
            total_duration = max(float(end) - float(start), 0.001)
        if count is not None and total_duration is not None:
            segment_seconds = max(float(total_duration) / max(int(count), 1), 0.1)
        if total_duration is not None:
            command.extend(["-t", f"{float(total_duration):.3f}"])
        elif end is not None:
            command.extend(["-to", f"{float(end):.3f}"])
        command.extend(
            [
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-c:v",
                str(self.params.get("video_codec", "libx264")),
                "-preset",
                str(self.params.get("preset", "veryfast")),
                "-crf",
                str(self.params.get("crf", 23)),
                "-c:a",
                str(self.params.get("audio_codec", "aac")),
                "-force_key_frames",
                f"expr:gte(t,n_forced*{segment_seconds:.3f})",
                "-sc_threshold",
                "0",
                "-f",
                "segment",
                "-segment_time",
                f"{segment_seconds:.3f}",
                "-reset_timestamps",
                "1",
                str(pattern),
            ]
        )
        run_ffmpeg(
            context,
            services,
            command,
        )
        outputs = [str(path) for path in sorted(output_dir.glob("segment_*.mp4"))]
        return _segments_result(output_dir, outputs)


def _segments_result(output_dir, outputs: list[str]) -> StepResult:
    if not outputs:
        raise RuntimeError("split_video produced no segments")
    missing = [path for path in outputs if not Path(path).exists()]
    if missing:
        raise RuntimeError(f"split_video did not create expected segment: {missing[0]}")
    return StepResult(
        context_patch={
            "output_video": str(output_dir),
            "metadata": {"segments": outputs},
            "state": {"skip_finalize": True},
        },
        artifacts={"segments": outputs},
    )
