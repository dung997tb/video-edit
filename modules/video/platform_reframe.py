from __future__ import annotations

from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


@register
class PlatformReframeModule(BaseModule):
    NAME = "platform_reframe"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services):
        preset = str(self.params.get("preset", "9:16"))
        width, height = _preset_size(preset, self.params)
        output_path = operation_output_path(context, self.params, self.NAME)
        x_expr, y_expr = _crop_position(self.params)
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}:{x_expr}:{y_expr}"
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


def _preset_size(preset: str, params: dict) -> tuple[int, int]:
    ratio = params.get("ratio") or params.get("aspect_ratio")
    if ratio:
        width = int(params.get("output_width", 1080))
        if params.get("output_height") is not None:
            return width, int(params["output_height"])
        return width, max(2, int(round(width / _parse_ratio(ratio))))
    if preset == "1:1":
        return int(params.get("output_width", 1080)), int(params.get("output_height", 1080))
    if preset == "16:9":
        return int(params.get("output_width", 1920)), int(params.get("output_height", 1080))
    return int(params.get("output_width", 1080)), int(params.get("output_height", 1920))


def _parse_ratio(value) -> float:
    text = str(value).strip()
    if ":" in text:
        left, right = text.split(":", 1)
        return max(float(left) / float(right), 0.01)
    return max(float(text), 0.01)


def _crop_position(params: dict) -> tuple[str, str]:
    if params.get("x") is not None or params.get("y") is not None:
        return str(params.get("x", "(iw-ow)/2")), str(params.get("y", "(ih-oh)/2"))
    anchor = str(params.get("anchor", "center")).lower()
    x_expr = "(iw-ow)/2"
    y_expr = "(ih-oh)/2"
    if "left" in anchor:
        x_expr = "0"
    elif "right" in anchor:
        x_expr = "iw-ow"
    if "top" in anchor:
        y_expr = "0"
    elif "bottom" in anchor:
        y_expr = "ih-oh"
    return x_expr, y_expr
