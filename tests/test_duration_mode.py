import unittest
from unittest.mock import patch

from modules.video.common import align_compose_clips, normalize_duration_mode


class DurationModeTests(unittest.TestCase):
    def test_hold_last_pads_shorter_clip(self) -> None:
        with self._patched_common() as calls:
            result = align_compose_clips(["a.mp4", "b.mp4"], duration_mode="hold_last", context=None, services=None)

        self.assertEqual(result, ["a.mp4", "b.mp4:padded:clone:10.0"])
        self.assertEqual(calls["pad"], [("b.mp4", 10.0, "clone")])

    def test_loop_repeats_shorter_clip(self) -> None:
        with self._patched_common() as calls:
            result = align_compose_clips(["a.mp4", "b.mp4"], duration_mode="loop", context=None, services=None)

        self.assertEqual(result, ["a.mp4", "b.mp4:looped:10.0"])
        self.assertEqual(calls["loop"], [("b.mp4", 10.0)])

    def test_trim_cuts_longer_clip_to_shortest(self) -> None:
        with self._patched_common() as calls:
            result = align_compose_clips(["a.mp4", "b.mp4"], duration_mode="trim", context=None, services=None)

        self.assertEqual(result, ["a.mp4:trimmed:3.0", "b.mp4"])
        self.assertEqual(calls["trim"], [("a.mp4", 3.0)])

    def test_shortest_is_trim_alias(self) -> None:
        with self._patched_common() as calls:
            result = align_compose_clips(["a.mp4", "b.mp4"], duration_mode="shortest", context=None, services=None)

        self.assertEqual(result, ["a.mp4:trimmed:3.0", "b.mp4"])
        self.assertEqual(calls["trim"], [("a.mp4", 3.0)])

    def test_pad_black_uses_black_padding(self) -> None:
        with self._patched_common() as calls:
            result = align_compose_clips(["a.mp4", "b.mp4"], duration_mode="pad_black", context=None, services=None)

        self.assertEqual(result, ["a.mp4", "b.mp4:padded:black:10.0"])
        self.assertEqual(calls["pad"], [("b.mp4", 10.0, "black")])

    def test_invalid_duration_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_duration_mode("forever")

    def _patched_common(self):
        durations = {"a.mp4": 10.0, "b.mp4": 3.0}
        calls = {"pad": [], "loop": [], "trim": []}

        class Patches:
            def __enter__(self_inner):
                def fake_pad(path, duration, *, mode, context, services, label):
                    calls["pad"].append((path, duration, mode))
                    return f"{path}:padded:{mode}:{duration}"

                def fake_loop(path, duration, *, context, services, label):
                    calls["loop"].append((path, duration))
                    return f"{path}:looped:{duration}"

                def fake_trim(path, duration, *, context, services, label):
                    calls["trim"].append((path, duration))
                    return f"{path}:trimmed:{duration}"

                self_inner.stack = [
                    patch("modules.video.common.probe_duration", side_effect=lambda path, context, services: durations[path]),
                    patch("modules.video.common.pad_video_to_duration", side_effect=fake_pad),
                    patch("modules.video.common.loop_video_to_duration", side_effect=fake_loop),
                    patch("modules.video.common.trim_video_to_duration", side_effect=fake_trim),
                ]
                for item in self_inner.stack:
                    item.__enter__()
                return calls

            def __exit__(self_inner, exc_type, exc, tb):
                for item in reversed(self_inner.stack):
                    item.__exit__(exc_type, exc, tb)

        return Patches()


if __name__ == "__main__":
    unittest.main()
