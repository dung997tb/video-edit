from __future__ import annotations

import unittest

from modules.video.scale import _build_scale_filter


class VideoScaleFilterTests(unittest.TestCase):
    def test_keep_aspect_filter_enforces_even_dimensions(self) -> None:
        vf = _build_scale_filter(width=854, height=480, keep_aspect=True)
        self.assertIn("force_original_aspect_ratio=decrease", vf)
        self.assertIn("force_divisible_by=2", vf)

    def test_single_dimension_filters_enforce_even_dimensions(self) -> None:
        vf_width = _build_scale_filter(width=1280, height=None, keep_aspect=True)
        vf_height = _build_scale_filter(width=None, height=720, keep_aspect=True)
        self.assertIn("force_divisible_by=2", vf_width)
        self.assertIn("force_divisible_by=2", vf_height)
