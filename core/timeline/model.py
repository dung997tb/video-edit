from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


TrackType = Literal["video", "audio", "subtitle"]


@dataclass(slots=True)
class Clip:
    source: str
    start: float = 0.0
    end: float | None = None
    track_start: float = 0.0
    duration: float | None = None
    volume: float = 1.0
    opacity: float = 1.0
    layout: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Clip":
        return cls(**data)


@dataclass(slots=True)
class SubtitleClip:
    text: str
    start: float
    end: float
    style: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubtitleClip":
        return cls(**data)


@dataclass(slots=True)
class Track:
    type: TrackType
    clips: list[Clip | SubtitleClip] = field(default_factory=list)
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
            "clips": [clip.to_dict() for clip in self.clips],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Track":
        track_type = data["type"]
        clip_cls = SubtitleClip if track_type == "subtitle" else Clip
        return cls(
            type=track_type,
            name=data.get("name"),
            clips=[clip_cls.from_dict(item) for item in data.get("clips", [])],
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(slots=True)
class Timeline:
    duration: float | None = None
    tracks: list[Track] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration": self.duration,
            "tracks": [track.to_dict() for track in self.tracks],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Timeline":
        return cls(
            duration=data.get("duration"),
            tracks=[Track.from_dict(item) for item in data.get("tracks", [])],
            metadata=dict(data.get("metadata", {})),
        )
