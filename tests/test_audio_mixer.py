import unittest

from modules.ai.audio_mixer import build_audio_filter_complex


class AudioMixerTests(unittest.TestCase):
    def test_single_track_audio_is_normalized_without_mix(self) -> None:
        self.assertEqual(build_audio_filter_complex(track_count=1), "[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[out]")

    def test_two_track_audio_is_normalized_and_mixed(self) -> None:
        filter_graph = build_audio_filter_complex(track_count=2, background_weight=0.15)
        self.assertIn("[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[a0]", filter_graph)
        self.assertIn("[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[a1]", filter_graph)
        self.assertIn("amix=inputs=2:duration=longest:weights='1 0.15'", filter_graph)
