from __future__ import annotations

from core.models import StepResult
from modules.base import BaseModule
from modules.registry import register


@register
class KaraokeSubtitleModule(BaseModule):
    NAME = "karaoke_subtitle"

    def upstream_artifact_hashes(self, context) -> dict:
        return {"segments": context.translated_segments or context.segments}

    def execute(self, context, services) -> StepResult:
        segments = context.translated_segments or context.segments
        if not segments:
            raise ValueError("segments are required before karaoke subtitle generation")
        output_path = context.file_manager.temp("04_karaoke.ass")
        style = _ass_style(
            font_size=int(self.params.get("font_size", 72)),
            active_color=str(self.params.get("active_color", "#FFFF00")),
        )
        lines = [_ass_header(style)]
        for segment in segments:
            text = _ass_escape(str(segment.get("text", "")).strip())
            lines.append(f"Dialogue: 0,{_ass_time(segment['start'])},{_ass_time(segment['end'])},Default,,0,0,0,,{text}")
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return StepResult(
            context_patch={"subtitle_path": str(output_path), "metadata": {"subtitle_style": "karaoke"}},
            artifacts={"subtitle": str(output_path)},
        )


def _ass_header(style: str) -> str:
    return "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            style,
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )


def _ass_style(*, font_size: int, active_color: str) -> str:
    color = _ass_color(active_color)
    return f"Style: Default,Arial,{font_size},{color},&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,140,1"


def _ass_color(hex_color: str) -> str:
    value = hex_color.strip().lstrip("#")
    if len(value) != 6:
        return "&H0000FFFF"
    rr, gg, bb = value[0:2], value[2:4], value[4:6]
    return f"&H00{bb}{gg}{rr}"


def _ass_time(seconds: float) -> str:
    total_cs = int(max(float(seconds), 0.0) * 100)
    hours, remainder = divmod(total_cs, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")
