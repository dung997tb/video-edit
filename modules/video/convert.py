from __future__ import annotations

from modules.base import BaseModule
from modules.registry import register
from modules.video.common import resolve_working_video, run_ffmpeg
from core.models import StepResult


CODEC_MAP = {
    "mp4": ("libx264", "aac"),
    "webm": ("libvpx-vp9", "libopus"),
    "avi": ("mpeg4", "mp3"),
    "mp3": (None, "libmp3lame"),
    "aac": (None, "aac"),
    "wav": (None, "pcm_s16le"),
}


@register
class ConvertModule(BaseModule):
    NAME = "convert"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services):
        output_format = str(self.params.get("output_format", "mp4")).lower().lstrip(".")
        if output_format not in CODEC_MAP:
            supported = ", ".join(sorted(CODEC_MAP))
            raise ValueError(f"unsupported output_format '{output_format}'. supported: {supported}")
        video_codec, audio_codec = CODEC_MAP[output_format]
        output_path = context.file_manager.output(f"final.{output_format}")
        command = [services.settings.ffmpeg_path, "-y", "-i", resolve_working_video(context)]
        if video_codec is None:
            command.extend(["-vn", "-c:a", audio_codec])
        else:
            command.extend(["-c:v", video_codec, "-c:a", audio_codec])
            if output_format == "mp4":
                command.extend(["-preset", "veryfast", "-crf", str(self.params.get("crf", 23)), "-movflags", "+faststart"])
        command.append(str(output_path))
        run_ffmpeg(context, services, command)
        return StepResult(
            context_patch={
                "output_video": str(output_path),
                "state": {"working_video": str(output_path), "skip_finalize": True},
            },
            artifacts={"output_video": str(output_path)},
        )
