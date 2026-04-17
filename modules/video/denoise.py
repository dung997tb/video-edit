from __future__ import annotations

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


@register
class DenoiseVideoModule(BaseModule):
    NAME = "denoise"

    def cache_inputs(self, context) -> dict:
        return {
            "luma_spatial": self.params.get("luma_spatial", 4),
            "chroma_spatial": self.params.get("chroma_spatial", 3),
            "luma_tmp": self.params.get("luma_tmp", 6),
            "chroma_tmp": self.params.get("chroma_tmp", 4),
        }

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services) -> StepResult:
        input_video = resolve_working_video(context)
        output_path = operation_output_path(context, self.params, self.NAME)
        luma_spatial = float(self.params.get("luma_spatial", 4))
        chroma_spatial = float(self.params.get("chroma_spatial", 3))
        luma_tmp = float(self.params.get("luma_tmp", 6))
        chroma_tmp = float(self.params.get("chroma_tmp", 4))
        vf = f"hqdn3d={luma_spatial}:{chroma_spatial}:{luma_tmp}:{chroma_tmp}"
        command = [
            services.settings.ffmpeg_path,
            "-y",
            "-i",
            input_video,
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(self.params.get("crf", 23)),
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        run_ffmpeg(context, services, command)
        return working_video_result(output_path)
