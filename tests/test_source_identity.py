from __future__ import annotations

import unittest

from core.artifact_store import LocalArtifactStore
from core.cache import sha256_bytes, sha256_text
from core.source_identity import resolve_source_sha256
from tests.helpers import make_test_root


class SourceIdentityTests(unittest.TestCase):
    def test_resolve_source_sha256_uses_existing_artifact_contents_for_source_key(self) -> None:
        root = make_test_root("source-identity-source-key")
        artifact_store = LocalArtifactStore(root / "artifacts")
        artifact_store.upload_bytes("uploads/demo/input.mp4", b"video-bytes")

        resolved = resolve_source_sha256(
            source_sha256=None,
            source_key="uploads/demo/input.mp4",
            artifact_store=artifact_store,
        )

        self.assertEqual(resolved, sha256_bytes(b"video-bytes"))

    def test_resolve_source_sha256_derives_stable_hash_for_input_uri(self) -> None:
        uri = "https://example.com/demo.mp4"

        resolved = resolve_source_sha256(
            source_sha256=None,
            input_uri=uri,
        )

        self.assertEqual(resolved, sha256_text(f"input_uri:{uri}"))
