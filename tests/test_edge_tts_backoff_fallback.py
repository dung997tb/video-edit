from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.models import JobStatus
from modules.ai.tts_backends.edge_tts_backend import EdgeTTSBackend
from tests.helpers import make_test_root


class EdgeTTSBackoffFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_test_root("edge-tts-test")
        self.output_path = self.root / "test_output.mp3"

    @patch("asyncio.sleep", return_value=None)
    @patch("edge_tts.Communicate")
    def test_edge_tts_success_on_first_try(self, mock_comm, mock_sleep) -> None:
        mock_instance = MagicMock()
        mock_comm.return_value = mock_instance
        
        async def mock_save(*args, **kwargs):
            return None
        mock_instance.save = mock_save

        backend = EdgeTTSBackend()
        backend.generate("Hello", self.output_path, voice="vi-VN-Neural", rate="+0%", volume="+0%")

        mock_comm.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("asyncio.sleep", return_value=None)
    @patch("edge_tts.Communicate")
    def test_edge_tts_backoff_succeeds_on_third_try(self, mock_comm, mock_sleep) -> None:
        mock_instance = MagicMock()
        mock_comm.return_value = mock_instance
        
        call_count = 0
        async def mock_save(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("Rate limited")
            return None
        mock_instance.save = mock_save

        backend = EdgeTTSBackend()
        backend.generate("Hello", self.output_path, voice="vi-VN-Neural", rate="+0%", volume="+0%")

        self.assertEqual(call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)

    @patch("asyncio.sleep", return_value=None)
    @patch("edge_tts.Communicate")
    @patch("modules.ai.tts_backends.openai_backend.OpenAITTSBackend.generate")
    def test_edge_tts_fallback_to_openai(self, mock_openai_gen, mock_comm, mock_sleep) -> None:
        mock_instance = MagicMock()
        mock_comm.return_value = mock_instance
        
        async def mock_save(*args, **kwargs):
            raise RuntimeError("Rate limited")
        mock_instance.save = mock_save

        # Config with OpenAI key
        settings = MagicMock()
        settings.openai_api_key = "fake-key"
        settings.openai_tts_model = "gpt-4o-mini-tts"
        
        backend = EdgeTTSBackend(settings=settings)
        backend.generate("Hello", self.output_path, voice="vi-VN-Neural", rate="+0%", volume="+0%")

        mock_openai_gen.assert_called_once_with("Hello", self.output_path, voice="vi-VN-Neural", rate="+0%", volume="+0%")

    @patch("asyncio.sleep", return_value=None)
    @patch("edge_tts.Communicate")
    @patch("urllib.request.urlopen")
    def test_edge_tts_fallback_to_google(self, mock_urlopen, mock_comm, mock_sleep) -> None:
        mock_instance = MagicMock()
        mock_comm.return_value = mock_instance
        
        async def mock_save(*args, **kwargs):
            raise RuntimeError("Rate limited")
        mock_instance.save = mock_save

        # Mock urllib response
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"fake audio bytes"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        backend = EdgeTTSBackend()
        backend.generate("Hello", self.output_path, voice="vi-VN-Neural", rate="+0%", volume="+0%")

        self.assertTrue(self.output_path.exists())
        self.assertEqual(self.output_path.read_bytes(), b"fake audio bytes")
        mock_urlopen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
