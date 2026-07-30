from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from govdata.core.entities import (
    Entity,
    EntityLink,
    EntityLinkedRecord,
    EntityProfile,
    EntityRecordReferences,
    EntityReference,
    EntitySummary,
)
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
                serialized_records = [
                    (
                        item.connector_id,
                        item.dataset,
                        item.external_id,
                        self._jsonb(dict(item.data)),
                        item.content_hash,
                        item.source_url,
                        item.collected_at,
                        item.source_updated_at,
                    )
                    for item in records
                ]
                cursor.executemany(
                    """
                    INSERT INTO record_versions (
                        connector_id, dataset, external_id, data_json, content_hash,
                        source_url, collected_at, source_updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(connector_id, dataset, external_id, content_hash) DO NOTHING
                    """,
                    serialized_records,
                )
                cursor.executemany(
                    """
                    INSERT INTO records (
                        connector_id, dataset, external_id, data_json,
                        collected_at, source_updated_at, source_url, content_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(connector_id, dataset, external_id) DO UPDATE SET
                        data_json = excluded.data_json,
                        collected_at = excluded.collected_at,
                        source_updated_at = excluded.source_updated_at,
                        source_url = excluded.source_url,
                        content_hash = excluded.content_hash
                    """,
                    [
                        (
                            connector_id,
                            dataset,
                            external_id,
                            data_json,
                            collected_at,
                            source_updated_at,
                            source_url,
                            item_hash,
                        )
                        for (
                            connector_id,
                            dataset,
                            external_id,
                            data_json,
                            item_hash,
                            source_url,
                            collected_at,
                            source_updated_at,
                        ) in serialized_records
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
                SELECT external_id, data_json, collected_at, source_updated_at,
                       source_url, content_hash
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
                "source_url": row[4],
                "content_hash": row[5],
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
                SELECT external_id, data_json, collected_at, source_updated_at,
                       source_url, content_hash
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
                    source_url=row[4],
                    content_hash=row[5] or "",
                )
                for row in rows
            ),
            total=total,
            limit=limit,
            offset=offset,
        )

    def record_entity_links(
        self,
        connector_id: str,
        dataset: str,
        external_id: str,
        refs: tuple[EntityReference, ...],
        observed_at: datetime,
    ) -> None:
        self.record_entity_links_batch(
            connector_id,
            dataset,
            (EntityRecordReferences(external_id, refs),),
            observed_at,
        )

    def record_entity_links_batch(
        self,
        connector_id: str,
        dataset: str,
        records: tuple[EntityRecordReferences, ...],
        observed_at: datetime,
    ) -> None:
        entity_rows = [
            (
                ref.entity_type,
                ref.entity_id,
                ref.display_name,
                observed_at,
                observed_at,
            )
            for record in records
            for ref in record.references
        ]
        link_rows = [
            (
                ref.entity_type,
                ref.entity_id,
                connector_id,
                dataset,
                record.external_id,
                ref.role,
                observed_at,
            )
            for record in records
            for ref in record.references
        ]
        if not entity_rows:
            return
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO entities (
                        entity_type, entity_id, display_name, first_seen_at, last_seen_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                        display_name = COALESCE(
                            excluded.display_name, entities.display_name
                        ),
                        last_seen_at = excluded.last_seen_at
                    """,
                    entity_rows,
                )
                cursor.executemany(
                    """
                    INSERT INTO entity_links (
                        entity_type, entity_id, connector_id, dataset, external_id,
                        role, linked_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(
                        entity_type, entity_id, connector_id, dataset, external_id
                    ) DO UPDATE SET
                        role = excluded.role,
                        linked_at = excluded.linked_at
                    """,
                    link_rows,
                )

    def get_entity_profile(self, entity_type: str, entity_id: str) -> EntityProfile | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT display_name, first_seen_at, last_seen_at FROM entities
                WHERE entity_type = %s AND entity_id = %s""",
                (entity_type, entity_id),
            ).fetchone()
            if row is None:
                return None
            links = connection.execute(
                """
                SELECT connector_id, dataset, external_id, role, linked_at
                FROM entity_links WHERE entity_type = %s AND entity_id = %s
                ORDER BY connector_id, dataset, external_id
                """,
                (entity_type, entity_id),
            ).fetchall()
        return EntityProfile(
            entity=Entity(
                entity_type=entity_type,
                entity_id=entity_id,
                display_name=row[0],
                first_seen_at=self._datetime(row[1]),
                last_seen_at=self._datetime(row[2]),
            ),
            links=tuple(
                EntityLink(
                    connector_id=link_row[0],
                    dataset=link_row[1],
                    external_id=link_row[2],
                    role=link_row[3],
                    linked_at=self._datetime(link_row[4]),
                )
                for link_row in links
            ),
        )

    def get_entity_records(
        self, entity_type: str, entity_id: str
    ) -> tuple[EntityLinkedRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    links.connector_id, links.dataset, links.external_id,
                    links.role, links.linked_at, records.data_json,
                    records.collected_at, records.source_updated_at,
                    records.source_url
                FROM entity_links AS links
                JOIN records
                  ON records.connector_id = links.connector_id
                 AND records.dataset = links.dataset
                 AND records.external_id = links.external_id
                WHERE links.entity_type = %s AND links.entity_id = %s
                ORDER BY records.collected_at DESC, links.external_id
                """,
                (entity_type, entity_id),
            ).fetchall()
        return tuple(
            EntityLinkedRecord(
                connector_id=row[0],
                dataset=row[1],
                external_id=row[2],
                role=row[3],
                linked_at=self._datetime(row[4]),
                data=row[5],
                collected_at=self._datetime(row[6]),
                source_updated_at=self._datetime(row[7]) if row[7] else None,
                source_url=row[8],
            )
            for row in rows
        )

    def search_entities(
        self, entity_type: str, query: str, limit: int
    ) -> tuple[EntitySummary, ...]:
        term = query.strip()
        if not term or limit < 1:
            return ()
        identifier = "".join(character for character in term if character.isdigit())
        identifier = identifier or term
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    entities.entity_id, entities.display_name,
                    entities.first_seen_at, entities.last_seen_at,
                    COUNT(entity_links.external_id) AS link_count
                FROM entities
                LEFT JOIN entity_links
                  ON entity_links.entity_type = entities.entity_type
                 AND entity_links.entity_id = entities.entity_id
                WHERE entities.entity_type = %s
                  AND (
                    entities.entity_id LIKE %s
                    OR COALESCE(entities.display_name, '') ILIKE %s
                  )
                GROUP BY
                    entities.entity_id, entities.display_name,
                    entities.first_seen_at, entities.last_seen_at
                ORDER BY
                    CASE
                        WHEN entities.entity_id = %s THEN 0
                        WHEN entities.entity_id LIKE %s THEN 1
                        WHEN COALESCE(entities.display_name, '') ILIKE %s THEN 2
                        ELSE 3
                    END,
                    link_count DESC,
                    entities.display_name,
                    entities.entity_id
                LIMIT %s
                """,
                (
                    entity_type,
                    f"%{identifier}%",
                    f"%{term}%",
                    identifier,
                    f"{identifier}%",
                    f"{term}%",
                    limit,
                ),
            ).fetchall()
        return tuple(
            EntitySummary(
                entity=Entity(
                    entity_type=entity_type,
                    entity_id=row[0],
                    display_name=row[1],
                    first_seen_at=self._datetime(row[2]),
                    last_seen_at=self._datetime(row[3]),
                ),
                link_count=row[4],
            )
            for row in rows
        )

    @staticmethod
    def _datetime(value: datetime | str) -> datetime:
        return value if isinstance(value, datetime) else datetime.fromisoformat(value)
