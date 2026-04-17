from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class ArtifactStore(ABC):
    @abstractmethod
    def exists(self, key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def upload_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        raise NotImplementedError

    @abstractmethod
    def download_bytes(self, key: str) -> bytes:
        raise NotImplementedError

    def upload_text(self, key: str, text: str, content_type: str = "text/plain") -> None:
        self.upload_bytes(key, text.encode("utf-8"), content_type=content_type)

    def download_text(self, key: str) -> str:
        return self.download_bytes(key).decode("utf-8")

    def upload_json(self, key: str, payload: dict[str, Any]) -> None:
        self.upload_text(key, json.dumps(payload, ensure_ascii=True, indent=2), content_type="application/json")

    def download_json(self, key: str) -> dict[str, Any]:
        return json.loads(self.download_text(key))

    def upload_file(self, key: str, local_path: str | Path, content_type: str = "application/octet-stream") -> None:
        self.upload_bytes(key, Path(local_path).read_bytes(), content_type=content_type)

    def download_file(self, key: str, local_path: str | Path) -> None:
        path = Path(local_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.download_bytes(key))


class LocalArtifactStore(ArtifactStore):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / key

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def upload_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def download_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()


class SupabaseArtifactStore(ArtifactStore):
    def __init__(self, client: Any, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    def exists(self, key: str) -> bool:
        folder, name = key.rsplit("/", 1) if "/" in key else ("", key)
        bucket = self.client.storage.from_(self.bucket)
        limit = 1000
        offset = 0
        try:
            while True:
                listing = bucket.list(folder or None, {"limit": limit, "offset": offset})
                if not listing:
                    return False
                if any(item.get("name") == name for item in listing):
                    return True
                if len(listing) < limit:
                    return False
                offset += len(listing)
        except Exception:
            return False

    def upload_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        bucket = self.client.storage.from_(self.bucket)
        if self.exists(key):
            bucket.update(key, data, {"content-type": content_type})
            return
        bucket.upload(key, data, {"content-type": content_type})

    def download_bytes(self, key: str) -> bytes:
        return self.client.storage.from_(self.bucket).download(key)
