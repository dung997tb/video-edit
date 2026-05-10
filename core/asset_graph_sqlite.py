from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core.asset_graph import AssetRecord


class SQLiteAssetGraph:
    def __init__(self, db_path: str | Path) -> None:
        self._db = Path(db_path)
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    parents TEXT DEFAULT '[]',
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_job ON assets(job_id)")

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
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO assets
                    (asset_id, job_id, node_id, uri, kind, parents, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    record.asset_id,
                    record.job_id,
                    record.node_id,
                    record.uri,
                    record.kind,
                    json.dumps(record.parents),
                    json.dumps(record.metadata),
                ),
            )
        return record

    def get(self, asset_id: str) -> AssetRecord | None:
        with sqlite3.connect(self._db) as conn:
            row = conn.execute(
                "SELECT asset_id, job_id, node_id, uri, kind, parents, metadata FROM assets WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
        return _row_to_record(row) if row else None

    def list_for_job(self, job_id: str) -> list[AssetRecord]:
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute(
                """
                SELECT asset_id, job_id, node_id, uri, kind, parents, metadata
                FROM assets
                WHERE job_id = ?
                ORDER BY created_at, asset_id
                """,
                (job_id,),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def children_of(self, parent_id: str) -> list[AssetRecord]:
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute(
                "SELECT asset_id, job_id, node_id, uri, kind, parents, metadata FROM assets ORDER BY created_at, asset_id"
            ).fetchall()
        records = [_row_to_record(row) for row in rows]
        return [record for record in records if parent_id in record.parents]


def _row_to_record(row: tuple) -> AssetRecord:
    return AssetRecord(
        asset_id=row[0],
        job_id=row[1],
        node_id=row[2],
        uri=row[3],
        kind=row[4],
        parents=list(json.loads(row[5] or "[]")),
        metadata=dict(json.loads(row[6] or "{}")),
    )
