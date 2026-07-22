from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from govdata.core.errors import DatabaseConfigurationError, PersistenceError
from govdata.core.models import RecordPage, StoredRecord
from govdata.infrastructure.migrations import load_migrations


class PostgresRecordRepository:
    def __init__(self, database_url: str) -> None:
        if not database_url.startswith(("postgres://", "postgresql://")):
            raise DatabaseConfigurationError("invalid PostgreSQL DATABASE_URL")
        self._database_url = database_url
        try:
            import psycopg
            from psycopg.types.json import Jsonb
        except ImportError as error:
            raise DatabaseConfigurationError(
                "PostgreSQL support is not installed; run "
                "python -m pip install -e '.[postgres]'"
            ) from error
        self._psycopg = psycopg
        self._jsonb = Jsonb
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        try:
            with self._psycopg.connect(self._database_url) as connection:
                yield connection
        except self._psycopg.Error as error:
            raise PersistenceError("PostgreSQL operation failed") from error

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(28473701)")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            applied = {
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            for version, script in load_migrations(
                "govdata.infrastructure.migrations.postgresql"
            ):
                if version in applied:
                    continue
                connection.execute(script)
                connection.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,),
                )

    def get_checkpoint(self, connector_id: str, dataset: str, scope: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT cursor FROM checkpoints
                WHERE connector_id = %s AND dataset = %s AND scope = %s""",
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
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO records (
                        connector_id, dataset, external_id, data_json,
                        collected_at, source_updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
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
                            self._jsonb(dict(item.data)),
                            item.collected_at,
                            item.source_updated_at,
                        )
                        for item in records
                    ],
                )
                cursor.execute(
                    """
                    INSERT INTO checkpoints (connector_id, dataset, scope, cursor)
                    VALUES (%s, %s, %s, %s)
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
                WHERE connector_id = %s AND dataset = %s AND scope = %s""",
                (connector_id, dataset, scope),
            )

    def list_records(
        self, connector_id: str, dataset: str, limit: int = 100
    ) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT external_id, data_json, collected_at, source_updated_at
                FROM records WHERE connector_id = %s AND dataset = %s
                ORDER BY external_id LIMIT %s
                """,
                (connector_id, dataset, limit),
            ).fetchall()
        return [
            {
                "external_id": row[0],
                "data": row[1],
                "collected_at": row[2].isoformat(),
                "source_updated_at": row[3].isoformat() if row[3] else None,
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
                WHERE connector_id = %s AND dataset = %s""",
                (connector_id, dataset),
            ).fetchone()[0]
            rows = connection.execute(
                """
                SELECT external_id, data_json, collected_at, source_updated_at
                FROM records WHERE connector_id = %s AND dataset = %s
                ORDER BY external_id LIMIT %s OFFSET %s
                """,
                (connector_id, dataset, limit, offset),
            ).fetchall()
        return RecordPage(
            records=tuple(
                StoredRecord(
                    connector_id=connector_id,
                    dataset=dataset,
                    external_id=row[0],
                    data=row[1],
                    collected_at=self._datetime(row[2]),
                    source_updated_at=self._datetime(row[3]) if row[3] else None,
                )
                for row in rows
            ),
            total=total,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def _datetime(value: datetime | str) -> datetime:
        return value if isinstance(value, datetime) else datetime.fromisoformat(value)
