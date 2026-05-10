from __future__ import annotations

from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, probe_duration, resolve_working_video, run_ffmpeg, working_video_result


@register
class AutoZoomModule(BaseModule):
    NAME = "auto_zoom"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services):
        width = int(self.params.get("output_width", 1080))
        height = int(self.params.get("output_height", 1920))
        interval = float(self.params.get("interval_seconds", self.params.get("interval", 4.0)))
        count = self.params.get("count") or self.params.get("times")
        if count is not None:
            duration = probe_duration(resolve_working_video(context), context, services)
            interval = max(duration / max(int(count), 1), 0.1)
        zoom_factor = float(self.params.get("zoom_factor", 1.1))
        transition = float(self.params.get("transition_duration", 0.3))
        fps = int(self.params.get("fps", 30))
        interval_frames = max(1, int(interval * fps))
        transition_frames = max(1, int(transition * fps))
        step = (max(zoom_factor, 1.0) - 1.0) / transition_frames
        output_path = operation_output_path(context, self.params, self.NAME)
        phase = f"mod(on\\,{interval_frames})"
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"zoompan=z='if(lte({phase}\\,{transition_frames})\\,"
            f"min({zoom_factor:.6f}\\,zoom+{step:.8f})\\,"
            f"if(lte({phase}\\,{transition_frames * 2})\\,max(1\\,zoom-{step:.8f})\\,zoom))':"
            f"d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        )
        run_ffmpeg(
            context,
            services,
            [
                services.settings.ffmpeg_path,
                "-y",
                "-i",
                resolve_working_video(context),
                "-vf",
                vf,
                "-c:a",
                "copy",
                str(output_path),
            ],
        )
        return working_video_result(output_path)
