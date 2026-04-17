import unittest

from core.artifact_store import SupabaseArtifactStore


class _ErrorBucket:
    def list(self, folder, options=None):
        raise RuntimeError(f"folder missing: {folder}")


class _ErrorStorage:
    def from_(self, bucket):
        return _ErrorBucket()


class _ErrorClient:
    storage = _ErrorStorage()


class _PagedBucket:
    def __init__(self) -> None:
        self._calls = 0

    def list(self, folder, options=None):
        self._calls += 1
        offset = int((options or {}).get("offset", 0))
        limit = int((options or {}).get("limit", 100))
        if offset == 0:
            return [{"name": f"file_{index}.bin"} for index in range(limit)]
        return [{"name": "target.bin"}]


class _PagedStorage:
    def __init__(self) -> None:
        self.bucket = _PagedBucket()

    def from_(self, bucket):
        return self.bucket


class _PagedClient:
    def __init__(self) -> None:
        self.storage = _PagedStorage()


class ArtifactStoreTests(unittest.TestCase):
    def test_supabase_exists_returns_false_when_folder_is_missing(self) -> None:
        store = SupabaseArtifactStore(_ErrorClient(), "artifacts")

        self.assertFalse(store.exists("jobs/job-1/final.mp4"))

    def test_supabase_exists_paginates_until_name_is_found(self) -> None:
        client = _PagedClient()
        store = SupabaseArtifactStore(client, "artifacts")

        self.assertTrue(store.exists("jobs/job-1/target.bin"))
