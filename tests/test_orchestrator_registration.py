from __future__ import annotations

import unittest

from orchestrators.factory import build_orchestrators


class OrchestratorRegistrationTests(unittest.TestCase):
    def test_upgrade_plan_pipelines_are_registered(self) -> None:
        orchestrators = build_orchestrators()

        self.assertIn("subtitle", orchestrators)
        self.assertIn("subtitle-only", orchestrators)
        self.assertIn("audio-extract", orchestrators)
        self.assertIn("audio_extract", orchestrators)
        self.assertIn("multilang-dubbing", orchestrators)
        self.assertIn("multilang_dubbing", orchestrators)
        self.assertIn("workflow", orchestrators)
        self.assertIn("semantic_edit", orchestrators)
        self.assertIn("silence_cut", orchestrators)
        self.assertIn("face_track_portrait", orchestrators)
        self.assertIn("auto_broll", orchestrators)
