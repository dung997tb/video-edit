from __future__ import annotations

import unittest

from core.secrets import InMemorySecretStore


class SecretStoreTests(unittest.TestCase):
    def test_in_memory_store_copies_job_secrets(self) -> None:
        store = InMemorySecretStore()
        store.put("job-old", {"payload.providers.tts.api_key": "secret"})

        store.copy("job-old", "job-new")

        self.assertEqual(store.get("job-new", "payload.providers.tts.api_key"), "secret")


if __name__ == "__main__":
    unittest.main()
