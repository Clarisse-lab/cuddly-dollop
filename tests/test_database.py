from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from govdata.bootstrap import create_repository
from govdata.core.errors import DatabaseConfigurationError
from govdata.core.models import StoredRecord
from govdata.infrastructure.migrations import load_migrations
from govdata.infrastructure.postgresql import PostgresRecordRepository
from govdata.infrastructure.sqlite import SQLiteRecordRepository


class DatabaseFactoryTests(unittest.TestCase):
    def test_defaults_to_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "default.sqlite3"
            with patch.dict(os.environ, {}, clear=True):
                repository = create_repository(path)

            self.assertIsInstance(repository, SQLiteRecordRepository)

    def test_accepts_sqlite_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "url.sqlite3"
            repository = create_repository(f"sqlite:///{path.as_posix()}")

            self.assertIsInstance(repository, SQLiteRecordRepository)
            self.assertTrue(path.exists())

    def test_uses_database_url_from_environment(self) -> None:
        sentinel = object()
        with (
            patch.dict(
                os.environ,
                {"DATABASE_URL": "postgresql://user:password@database/govdata"},
                clear=True,
            ),
            patch("govdata.bootstrap.PostgresRecordRepository", return_value=sentinel) as factory,
        ):
            repository = create_repository()

        self.assertIs(repository, sentinel)
        factory.assert_called_once_with("postgresql://user:password@database/govdata")

    def test_rejects_unknown_database_scheme(self) -> None:
        with self.assertRaises(DatabaseConfigurationError):
            create_repository("mysql://database/govdata")

    def test_postgres_repository_rejects_non_postgres_url(self) -> None:
        with self.assertRaises(DatabaseConfigurationError):
            PostgresRecordRepository("sqlite:///local.sqlite3")


class SQLiteMigrationTests(unittest.TestCase):
    def test_applies_all_migrations_once_and_preserves_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "migrations.sqlite3"
            repository = SQLiteRecordRepository(path)
            repository.commit_page(
                "source",
                "items",
                "scope",
                (
                    StoredRecord(
                        connector_id="source",
                        dataset="items",
                        external_id="1",
                        data={"name": "kept"},
                        collected_at=datetime(2026, 7, 21, tzinfo=UTC),
                    ),
                ),
                None,
            )

            SQLiteRecordRepository(path)

            with closing(sqlite3.connect(path)) as connection:
                versions = connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                ).fetchall()
                count = connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            self.assertEqual(
                [row[0] for row in versions],
                [
                    "001_records.sql",
                    "002_checkpoints.sql",
                    "003_record_history.sql",
                    "004_entities.sql",
                ],
            )
            self.assertEqual(count, 1)

    def test_preserves_only_distinct_record_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.sqlite3"
            repository = SQLiteRecordRepository(path)
            collected_at = datetime(2026, 7, 22, tzinfo=UTC)

            for name in ("first", "first", "changed"):
                repository.commit_page(
                    "source",
                    "items",
                    "scope",
                    (
                        StoredRecord(
                            connector_id="source",
                            dataset="items",
                            external_id="1",
                            data={"name": name},
                            source_url="https://example.gov/item/1",
                            collected_at=collected_at,
                        ),
                    ),
                    None,
                )

            with closing(sqlite3.connect(path)) as connection:
                version_count = connection.execute(
                    "SELECT COUNT(*) FROM record_versions"
                ).fetchone()[0]
                current = connection.execute(
                    "SELECT data_json, source_url, content_hash FROM records"
                ).fetchone()

            self.assertEqual(version_count, 2)
            self.assertEqual(current[1], "https://example.gov/item/1")
            self.assertTrue(current[2])
            self.assertEqual(current[0], '{"name": "changed"}')

    def test_packages_migrations_for_both_engines(self) -> None:
        sqlite_versions = load_migrations("govdata.infrastructure.migrations.sqlite")
        postgres_versions = load_migrations("govdata.infrastructure.migrations.postgresql")

        self.assertEqual(
            [item[0] for item in sqlite_versions],
            [item[0] for item in postgres_versions],
        )
        self.assertIn("JSONB", postgres_versions[0][1])


if __name__ == "__main__":
    unittest.main()
