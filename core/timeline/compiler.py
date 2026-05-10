from __future__ import annotations

from pathlib import Path

from core.timeline.model import Clip, SubtitleClip, Timeline


class TimelineCompiler:
    def __init__(self, timeline: Timeline) -> None:
        self.timeline = timeline

    def primary_video(self) -> Clip | None:
        for track in self.timeline.tracks:
            if track.type == "video" and track.clips:
                return track.clips[0]  # type: ignore[return-value]
        return None

    def subtitle_clips(self) -> list[SubtitleClip]:
        clips: list[SubtitleClip] = []
        for track in self.timeline.tracks:
            if track.type == "subtitle":
                clips.extend(clip for clip in track.clips if isinstance(clip, SubtitleClip))
        return clips

    def write_srt(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        for index, clip in enumerate(self.subtitle_clips(), start=1):
            lines.append(str(index))
            lines.append(f"{_srt_timestamp(clip.start)} --> {_srt_timestamp(clip.end)}")
            lines.append(clip.text)
            lines.append("")
        destination.write_text("\n".join(lines), encoding="utf-8")
        return destination

    def simple_render_command(self, ffmpeg_path: str, output_path: str | Path) -> list[str]:
        video = self.primary_video()
        if video is None:
            raise ValueError("timeline render requires at least one video clip")
        command = [ffmpeg_path, "-y", "-ss", f"{video.start:.3f}", "-i", video.source]
        if video.end is not None:
            command.extend(["-t", f"{max(video.end - video.start, 0.001):.3f}"])
        command.extend(["-c", "copy", str(output_path)])
        return command


def _srt_timestamp(seconds: float) -> str:
    total_ms = int(max(seconds, 0.0) * 1000)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"
