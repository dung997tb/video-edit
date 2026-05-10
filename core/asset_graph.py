from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class AssetRecord:
    asset_id: str
    job_id: str
    node_id: str
    uri: str
    kind: str
    parents: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class InMemoryAssetGraph:
    def __init__(self) -> None:
        self._records: dict[str, AssetRecord] = {}

    def record(
        self,
        *,
        asset_id: str,
        job_id: str,
        node_id: str,
        uri: str,
        kind: str,
        parents: list[str] | None = None,
        metadata: dict | None = None,
    ) -> AssetRecord:
        record = AssetRecord(
            asset_id=asset_id,
            job_id=job_id,
            node_id=node_id,
            uri=uri,
            kind=kind,
            parents=parents or [],
            metadata=metadata or {},
        )
        self._records[asset_id] = record
        return record

    def get(self, asset_id: str) -> AssetRecord | None:
        return self._records.get(asset_id)

    def list_for_job(self, job_id: str) -> list[AssetRecord]:
        return [record for record in self._records.values() if record.job_id == job_id]

    def children_of(self, parent_id: str) -> list[AssetRecord]:
        return [record for record in self._records.values() if parent_id in record.parents]
