from __future__ import annotations

from modules.video.common import atempo_chain
from modules.base import BaseModule
from modules.registry import register
from modules.video.common import operation_output_path, resolve_working_video, run_ffmpeg, working_video_result


@register
class ContentVariantModule(BaseModule):
    NAME = "content_variant"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_video": resolve_working_video(context)}

    def execute(self, context, services):
        speed = float(self.params.get("speed_factor", 1.0))
        rotation = float(self.params.get("rotation_degree", 0.0))
        noise = float(self.params.get("grain", self.params.get("noise_strength", 3)))
        hue = float(self.params.get("hue_shift", self.params.get("color_shift", 2.0)))
        saturation = float(self.params.get("sat_factor", self.params.get("saturation", 1.02)))
        audio_shift_cents = float(self.params.get("audio_shift_cents", 0))
        sample_rate = int(self.params.get("sample_rate", 44100))
        filters = []
        if abs(speed - 1.0) > 1e-6:
            filters.append(f"setpts=PTS/{speed}")
        if abs(rotation) > 1e-6:
            filters.append(f"rotate={rotation}*PI/180:ow=iw:oh=ih:c=black")
        if noise > 0:
            filters.append(f"noise=c0s={noise}:c0f=t+u")
        if abs(hue) > 1e-6 or abs(saturation - 1.0) > 1e-6:
            filters.append(f"hue=h={hue}:s={saturation}")
        output_path = operation_output_path(context, self.params, self.NAME)
        command = [services.settings.ffmpeg_path, "-y", "-i", resolve_working_video(context)]
        if filters:
            command.extend(["-vf", ",".join(filters)])
        audio_filters: list[str] = []
        pitch_factor = 2 ** (audio_shift_cents / 1200.0)
        if abs(audio_shift_cents) > 1e-6:
            audio_filters.extend([f"asetrate={sample_rate}*{pitch_factor:.8f}", f"aresample={sample_rate}"])
        tempo_factor = speed / pitch_factor
        if abs(tempo_factor - 1.0) > 1e-6:
            audio_filters.extend(atempo_chain(tempo_factor))
        command.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                str(self.params.get("crf", 23)),
            ]
        )
        if audio_filters:
            command.extend(["-af", ",".join(audio_filters), "-c:a", "aac"])
        else:
            command.extend(["-c:a", "copy"])
        command.extend(["-movflags", "+faststart", str(output_path)])
        run_ffmpeg(context, services, command)
        return working_video_result(output_path)
