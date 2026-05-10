from __future__ import annotations

from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


@register
class DelogoModule(BaseModule):
    NAME = "delogo"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services):
        x = int(self.params["x"])
        y = int(self.params["y"])
        width = int(self.params["w"])
        height = int(self.params["h"])
        mode = str(self.params.get("mode", "blur"))
        strength = float(self.params.get("strength", self.params.get("blur_strength", 15)))
        enable = _enable_expr(self.params)
        if mode == "blur":
            overlay_args = f"{x}:{y}"
            if enable:
                overlay_args += f":enable='{enable}'"
            vf = (
                f"split[m][b];"
                f"[b]crop={width}:{height}:{x}:{y},boxblur={strength}:5[blr];"
                f"[m][blr]overlay={overlay_args}"
            )
        else:
            vf = f"delogo=x={x}:y={y}:w={width}:h={height}"
            if enable:
                vf += f":enable='{enable}'"
        output_path = operation_output_path(context, self.params, self.NAME)
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


def _enable_expr(params: dict) -> str | None:
    start = params.get("start")
    end = params.get("end")
    duration = params.get("duration")
    time_range = params.get("time_range")
    if isinstance(time_range, dict):
        start = time_range.get("start", start)
        end = time_range.get("end", end)
        duration = time_range.get("duration", duration)
    if start is None and end is None and duration is None:
        return None
    start_value = float(start or 0)
    if end is None and duration is not None:
        end = start_value + float(duration)
    if end is None:
        return f"gte(t\\,{start_value:.3f})"
    return f"between(t\\,{start_value:.3f}\\,{float(end):.3f})"
