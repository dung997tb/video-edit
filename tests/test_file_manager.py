import unittest

from core.file_manager import FileManager
from tests.helpers import make_test_root


class FileManagerTests(unittest.TestCase):
    def test_step_file_naming_convention(self) -> None:
        root = make_test_root("file-manager")
        manager = FileManager(root / "temp", root / "output", "job-123")

        self.assertEqual(manager.step_file("extract_audio").name, "01_extract_audio.wav")
        self.assertEqual(manager.step_file("transcript").name, "02_transcript.json")
        self.assertEqual(manager.step_file("translate").name, "03_translate.json")
        self.assertEqual(manager.step_file("subtitle").name, "04_subtitle.srt")
        self.assertEqual(manager.step_file("tts", n=7).name, "05_tts_007.wav")
        self.assertEqual(manager.step_file("synced_audio").name, "06_synced.wav")
        self.assertEqual(manager.step_file("mixed_audio").name, "07_mixed.wav")
        self.assertEqual(manager.step_file("final").name, "final.mp4")
