from __future__ import annotations

import math

from core.ffmpeg_filters import atempo_chain
from modules.audio.common import operation_output_path, resolve_working_audio, run_ffmpeg, working_audio_result
from modules.base import BaseModule
from modules.registry import register


@register
class AudioPitchModule(BaseModule):
    NAME = "audio_pitch"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"working_audio": resolve_working_audio(context)}

    def execute(self, context, services):
        input_audio = resolve_working_audio(context)
        if not input_audio:
            raise ValueError("audio_pitch requires a source audio in context")
        semitones = float(self.params.get("semitones", 1.0))
        preserve_tempo = bool(self.params.get("preserve_tempo", True))
        sample_rate = int(self.params.get("sample_rate", 44100))
        factor = 2 ** (semitones / 12.0)
        filters = [f"asetrate={sample_rate}*{factor:.8f}", f"aresample={sample_rate}"]
        if preserve_tempo and not math.isclose(factor, 1.0):
            filters.extend(atempo_chain(1 / factor))
        output_path = operation_output_path(context, self.params, self.NAME)
        run_ffmpeg(
            context,
            services,
            [
                services.settings.ffmpeg_path,
                "-y",
                "-i",
                input_audio,
                "-af",
                ",".join(filters),
                str(output_path),
            ],
        )
        return working_audio_result(output_path)
