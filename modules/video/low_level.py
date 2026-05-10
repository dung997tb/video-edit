from __future__ import annotations

from typing import Any

from modules.audio.audio_fade import AudioFadeModule
from modules.audio.audio_normalize import AudioNormalizeModule
from modules.audio.audio_pitch import AudioPitchModule
from modules.audio.audio_speed import AudioSpeedModule
from modules.audio.audio_trim import AudioTrimModule
from modules.audio.audio_volume import AudioVolumeModule
from modules.video.auto_zoom import AutoZoomModule
from modules.video.blur_bg_portrait import BlurBgPortraitModule
from modules.visual.blur import VisualBlurModule
from modules.visual.grayscale import VisualGrayscaleModule
from modules.visual.sharpen import VisualSharpenModule
from modules.visual.vignette import VisualVignetteModule
from modules.video.color_grade import ColorGradeVideoModule
from modules.video.concat import ConcatVideoModule
from modules.video.content_variant import ContentVariantModule
from modules.video.chromakey import ChromakeyModule
from modules.video.convert import ConvertModule
from modules.video.crop import CropVideoModule
from modules.video.cut import CutVideoModule
from modules.video.delogo import DelogoModule
from modules.video.denoise import DenoiseVideoModule
from modules.video.extract_frames import ExtractFramesModule
from modules.video.filter_duration import FilterDurationModule
from modules.video.finalize import FinalizeVideoModule
from modules.video.flip import FlipVideoModule
from modules.video.grid import GridModule
from modules.video.hstack import HStackModule
from modules.video.loop import LoopVideoModule
from modules.video.overlay import OverlayVideoModule
from modules.video.pad_border import PadBorderModule
from modules.video.platform_reframe import PlatformReframeModule
from modules.video.random_mirror import RandomMirrorModule
from modules.video.rotate import RotateVideoModule
from modules.video.scale import ScaleVideoModule
from modules.video.split_screen import SplitScreenModule
from modules.video.split_video import SplitVideoModule
from modules.video.speed import SpeedVideoModule
from modules.video.watermark import WatermarkVideoModule


VIDEO_OPERATION_MODULES: dict[str, type] = {
    "cut": CutVideoModule,
    "speed": SpeedVideoModule,
    "flip": FlipVideoModule,
    "crop": CropVideoModule,
    "rotate": RotateVideoModule,
    "scale": ScaleVideoModule,
    "concat": ConcatVideoModule,
    "overlay": OverlayVideoModule,
    "watermark": WatermarkVideoModule,
    "denoise": DenoiseVideoModule,
    "color_grade": ColorGradeVideoModule,
    "pad_border": PadBorderModule,
    "blur_bg_portrait": BlurBgPortraitModule,
    "loop": LoopVideoModule,
    "filter_duration": FilterDurationModule,
    "extract_frames": ExtractFramesModule,
    "delogo": DelogoModule,
    "content_variant": ContentVariantModule,
    "hstack": HStackModule,
    "split_screen": SplitScreenModule,
    "split_video": SplitVideoModule,
    "chromakey": ChromakeyModule,
    "grid": GridModule,
    "convert": ConvertModule,
    "random_mirror": RandomMirrorModule,
    "platform_reframe": PlatformReframeModule,
    "auto_zoom": AutoZoomModule,
    "audio_trim": AudioTrimModule,
    "audio_speed": AudioSpeedModule,
    "audio_volume": AudioVolumeModule,
    "audio_fade": AudioFadeModule,
    "audio_normalize": AudioNormalizeModule,
    "audio_pitch": AudioPitchModule,
    "visual_blur": VisualBlurModule,
    "visual_sharpen": VisualSharpenModule,
    "visual_grayscale": VisualGrayscaleModule,
    "visual_vignette": VisualVignetteModule,
}


def build_low_level_pipeline(job, services):
    payload = job.payload or {}
    operations = payload.get("operations", [])
    if not isinstance(operations, list) or not operations:
        raise ValueError("low_level pipeline requires payload.operations as a non-empty list")
    pipeline: list[Any] = []
    for index, operation in enumerate(operations, start=1):
        if not isinstance(operation, dict):
            raise ValueError(f"operation #{index} must be an object")
        params = _flatten_operation(operation)
        op_name = str(params.get("name", params.get("type", ""))).strip().lower()
        module_cls = VIDEO_OPERATION_MODULES.get(op_name)
        if module_cls is None:
            supported = ", ".join(sorted(VIDEO_OPERATION_MODULES.keys()))
            raise ValueError(f"unsupported low_level operation '{op_name}'. supported: {supported}")
        params.pop("name", None)
        params.pop("type", None)
        params["op_index"] = index
        pipeline.append(module_cls(params=params))
    pipeline.append(FinalizeVideoModule(params={"op_index": len(pipeline) + 1}))
    return pipeline


def _flatten_operation(operation: dict[str, Any]) -> dict[str, Any]:
    nested = operation.get("params", {})
    if nested is None:
        nested = {}
    if not isinstance(nested, dict):
        raise ValueError("operation params must be an object")
    params = dict(nested)
    for key, value in operation.items():
        if key == "params":
            continue
        if key == "type":
            params.setdefault("name", value)
            params["type"] = value
            continue
        if key == "id":
            params.setdefault("operation_id", value)
        params[key] = value
    return params
