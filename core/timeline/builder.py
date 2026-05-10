from __future__ import annotations

from core.timeline.model import Clip, SubtitleClip, Timeline, Track


class TimelineBuilder:
    def __init__(self, duration: float | None = None) -> None:
        self.timeline = Timeline(duration=duration)

    def add_video(self, source: str, *, start: float = 0.0, end: float | None = None, track_start: float = 0.0, **metadata):
        self._track("video").clips.append(Clip(source=source, start=start, end=end, track_start=track_start, metadata=metadata))
        return self

    def add_audio(
        self,
        source: str,
        *,
        start: float = 0.0,
        end: float | None = None,
        track_start: float = 0.0,
        volume: float = 1.0,
        **metadata,
    ):
        self._track("audio").clips.append(
            Clip(source=source, start=start, end=end, track_start=track_start, volume=volume, metadata=metadata)
        )
        return self

    def add_subtitle(self, text: str, *, start: float, end: float, style: str = "default", **metadata):
        self._track("subtitle").clips.append(SubtitleClip(text=text, start=start, end=end, style=style, metadata=metadata))
        return self

    def build(self) -> Timeline:
        return self.timeline

    def _track(self, track_type: str) -> Track:
        for track in self.timeline.tracks:
            if track.type == track_type:
                return track
        track = Track(type=track_type)
        self.timeline.tracks.append(track)
        return track
