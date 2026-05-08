from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from modules.ai.tts_backends.base import TTSBackend


class GoogleCloudTTSBackend(TTSBackend):
    def __init__(self, *, api_key: str | None) -> None:
        self.api_key = api_key

    def generate(self, text: str, output_path: Path, *, voice: str, rate: str, volume: str) -> None:
        if not self.api_key:
            raise RuntimeError("GOOGLE_CLOUD_TTS_KEY is required for TTS_ENGINE=google-cloud")
        language_code = "-".join(voice.split("-")[:2]) if "-" in voice else "en-US"
        payload = {
            "input": {"text": text},
            "voice": {"languageCode": language_code, "name": voice},
            "audioConfig": {
                "audioEncoding": "MP3",
                "speakingRate": _parse_percent(rate, default=1.0),
                "volumeGainDb": _parse_volume_db(volume),
            },
        }
        url = "https://texttospeech.googleapis.com/v1/text:synthesize?" + urlencode({"key": self.api_key})
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        output_path.write_bytes(base64.b64decode(data["audioContent"]))


def _parse_percent(value: str, *, default: float) -> float:
    try:
        raw = str(value).strip()
        if raw.endswith("%"):
            return max(0.25, min(4.0, default + (float(raw[:-1]) / 100.0)))
        return max(0.25, min(4.0, float(raw)))
    except (TypeError, ValueError):
        return default


def _parse_volume_db(value: str) -> float:
    try:
        raw = str(value).strip()
        if raw.endswith("%"):
            return max(-96.0, min(16.0, float(raw[:-1]) / 5.0))
        return max(-96.0, min(16.0, float(raw)))
    except (TypeError, ValueError):
        return 0.0
