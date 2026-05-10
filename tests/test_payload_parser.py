import unittest

from core.key_redactor import split_redacted_secrets
from core.payload_parser import parse_job_payload


class PayloadParserTests(unittest.TestCase):
    def test_structured_operation_is_flattened_for_low_level_pipeline(self) -> None:
        payload = parse_job_payload(
            {
                "time_range": {"start": 2, "duration": 5},
                "operations": [
                    {
                        "id": "blur-1",
                        "type": "delogo",
                        "params": {"x": 10, "y": 20, "w": 100, "h": 80},
                    }
                ],
            }
        )

        self.assertEqual(payload["operations"][0]["name"], "delogo")
        self.assertEqual(payload["operations"][0]["operation_id"], "blur-1")
        self.assertEqual(payload["operations"][0]["x"], 10)
        self.assertEqual(payload["operations"][0]["start"], 2.0)
        self.assertEqual(payload["operations"][0]["duration"], 5.0)
        self.assertEqual(payload["operations"][0]["end"], 7.0)

    def test_redacts_provider_api_key_and_extracts_secret(self) -> None:
        payload = {
            "providers": {
                "tts": {
                    "provider": "elevenlabs",
                    "api_key": "secret-123456",
                }
            }
        }

        redacted, secrets = split_redacted_secrets(payload)

        self.assertEqual(redacted["providers"]["tts"]["api_key"], "***3456")
        self.assertEqual(redacted["providers"]["tts"]["api_key_source"], "request")
        self.assertEqual(secrets["providers.tts.api_key"], "secret-123456")

    def test_rejects_invalid_time_range(self) -> None:
        with self.assertRaises(ValueError):
            parse_job_payload({"time_range": {"start": 10, "end": 2}})


if __name__ == "__main__":
    unittest.main()
