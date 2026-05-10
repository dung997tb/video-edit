from __future__ import annotations

import unittest

from core.timeline import Timeline, TimelineBuilder, TimelineCompiler


class TimelineTests(unittest.TestCase):
    def test_timeline_round_trips(self) -> None:
        timeline = (
            TimelineBuilder(duration=10)
            .add_video("main.mp4", start=1, end=6)
            .add_audio("voice.wav", volume=0.8)
            .add_subtitle("Hello", start=1.2, end=2.4, style="karaoke")
            .build()
        )

        restored = Timeline.from_dict(timeline.to_dict())

        self.assertEqual(restored.duration, 10)
        self.assertEqual(len(restored.tracks), 3)

    def test_simple_render_command_uses_primary_clip(self) -> None:
        timeline = TimelineBuilder().add_video("main.mp4", start=2, end=5).build()

        command = TimelineCompiler(timeline).simple_render_command("ffmpeg", "out.mp4")

        self.assertIn("-ss", command)
        self.assertIn("2.000", command)
        self.assertIn("-t", command)
        self.assertIn("3.000", command)
