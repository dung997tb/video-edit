from __future__ import annotations

from typing import Any

from modules.audio.audio_fade import AudioFadeModule
from modules.audio.audio_normalize import AudioNormalizeModule
from modules.audio.audio_speed import AudioSpeedModule
from modules.audio.audio_trim import AudioTrimModule
from modules.audio.audio_volume import AudioVolumeModule
from modules.visual.blur import VisualBlurModule
from modules.visual.grayscale import VisualGrayscaleModule
from modules.visual.sharpen import VisualSharpenModule
from modules.visual.vignette import VisualVignetteModule
from modules.video.color_grade import ColorGradeVideoModule
from modules.video.concat import ConcatVideoModule
from modules.video.crop import CropVideoModule
from modules.video.cut import CutVideoModule
from modules.video.denoise import DenoiseVideoModule
from modules.video.finalize import FinalizeVideoModule
from modules.video.flip import FlipVideoModule
from modules.video.overlay import OverlayVideoModule
from modules.video.rotate import RotateVideoModule
from modules.video.scale import ScaleVideoModule
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
    "audio_trim": AudioTrimModule,
    "audio_speed": AudioSpeedModule,
    "audio_volume": AudioVolumeModule,
    "audio_fade": AudioFadeModule,
    "audio_normalize": AudioNormalizeModule,
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
        op_name = str(operation.get("name", "")).strip().lower()
        module_cls = VIDEO_OPERATION_MODULES.get(op_name)
        if module_cls is None:
            supported = ", ".join(sorted(VIDEO_OPERATION_MODULES.keys()))
            raise ValueError(f"unsupported low_level operation '{op_name}'. supported: {supported}")
        params = dict(operation)
        params.pop("name", None)
        params["op_index"] = index
        pipeline.append(module_cls(params=params))
    pipeline.append(FinalizeVideoModule(params={"op_index": len(pipeline) + 1}))
    return pipeline
