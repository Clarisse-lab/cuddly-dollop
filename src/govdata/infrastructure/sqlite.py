from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from govdata.core.models import RecordPage, StoredRecord


class SQLiteRecordRepository:
    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS records (
                    connector_id TEXT NOT NULL,
                    dataset TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    source_updated_at TEXT,
                    PRIMARY KEY (connector_id, dataset, external_id)
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                    connector_id TEXT NOT NULL,
                    dataset TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    cursor TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (connector_id, dataset, scope)
                );
                """
            )

    def get_checkpoint(self, connector_id: str, dataset: str, scope: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT cursor FROM checkpoints
                WHERE connector_id = ? AND dataset = ? AND scope = ?""",
                (connector_id, dataset, scope),
            ).fetchone()
        return row[0] if row else None

    def commit_page(
        self,
        connector_id: str,
        dataset: str,
        scope: str,
        records: tuple[StoredRecord, ...],
        next_cursor: str | None,
    ) -> int:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO records (
                    connector_id, dataset, external_id, data_json,
                    collected_at, source_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(connector_id, dataset, external_id) DO UPDATE SET
                    data_json = excluded.data_json,
                    collected_at = excluded.collected_at,
                    source_updated_at = excluded.source_updated_at
                """,
                [
                    (
                        item.connector_id,
                        item.dataset,
                        item.external_id,
                        json.dumps(dict(item.data), ensure_ascii=False, sort_keys=True),
                        item.collected_at.isoformat(),
                        item.source_updated_at.isoformat() if item.source_updated_at else None,
                    )
                    for item in records
                ],
            )
            connection.execute(
                """
                INSERT INTO checkpoints (connector_id, dataset, scope, cursor)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(connector_id, dataset, scope) DO UPDATE SET
                    cursor = excluded.cursor,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (connector_id, dataset, scope, next_cursor),
            )
        return len(records)

    def clear_checkpoint(self, connector_id: str, dataset: str, scope: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """DELETE FROM checkpoints
                WHERE connector_id = ? AND dataset = ? AND scope = ?""",
                (connector_id, dataset, scope),
            )

    def list_records(
        self, connector_id: str, dataset: str, limit: int = 100
    ) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT external_id, data_json, collected_at, source_updated_at
                FROM records WHERE connector_id = ? AND dataset = ?
                ORDER BY external_id LIMIT ?
                """,
                (connector_id, dataset, limit),
            ).fetchall()
        return [
            {
                "external_id": row[0],
                "data": json.loads(row[1]),
                "collected_at": row[2],
                "source_updated_at": row[3],
            }
            for row in rows
        ]

    def query_records(
        self,
        connector_id: str,
        dataset: str,
        *,
        limit: int,
        offset: int,
    ) -> RecordPage:
        with self._connect() as connection:
            total = connection.execute(
                """SELECT COUNT(*) FROM records
                WHERE connector_id = ? AND dataset = ?""",
                (connector_id, dataset),
            ).fetchone()[0]
            rows = connection.execute(
                """
                SELECT external_id, data_json, collected_at, source_updated_at
                FROM records WHERE connector_id = ? AND dataset = ?
                ORDER BY external_id LIMIT ? OFFSET ?
                """,
                (connector_id, dataset, limit, offset),
            ).fetchall()
        return RecordPage(
            records=tuple(
                StoredRecord(
                    connector_id=connector_id,
                    dataset=dataset,
                    external_id=row[0],
                    data=json.loads(row[1]),
                    collected_at=datetime.fromisoformat(row[2]),
                    source_updated_at=(
                        datetime.fromisoformat(row[3]) if row[3] is not None else None
                    ),
                )
                for row in rows
            ),
            total=total,
            limit=limit,
            offset=offset,
        )
