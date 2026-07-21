from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

from govdata.application.sync import SyncService
from govdata.core.errors import DatasetNotSupportedError, InvalidResponseError
from govdata.core.models import ConnectorPage, ConnectorRecord, ConnectorSpec, SyncRequest
from govdata.core.ports import HttpClient, PublicDataConnector
from govdata.core.registry import ConnectorRegistry
from govdata.infrastructure.sqlite import SQLiteRecordRepository


class FakeConnector(PublicDataConnector):
    spec = ConnectorSpec(id="fake", display_name="Fake", datasets=("items",))
    requested_cursors: list[str | None] = []

    async def fetch_page(
        self,
        dataset: str,
        parameters: Mapping[str, Any],
        cursor: str | None,
        http: HttpClient,
    ) -> ConnectorPage:
        self.requested_cursors.append(cursor)
        if cursor is None:
            return ConnectorPage(
                records=(ConnectorRecord("1", {"name": "first"}),), next_cursor="page-2"
            )
        return ConnectorPage(records=(ConnectorRecord("2", {"name": "second"}),))


class RepeatingCursorConnector(FakeConnector):
    spec = ConnectorSpec(id="repeat", display_name="Repeat", datasets=("items",))

    async def fetch_page(self, dataset, parameters, cursor, http):  # type: ignore[no-untyped-def]
        return ConnectorPage(records=(), next_cursor="same")


class SyncServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = SQLiteRecordRepository(Path(self.temp.name) / "test.sqlite3")
        self.registry = ConnectorRegistry()
        self.registry.register(FakeConnector)
        self.service = SyncService(self.registry, self.repository, object())  # type: ignore[arg-type]
        FakeConnector.requested_cursors = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_syncs_pages_and_upserts_records(self) -> None:
        result = asyncio.run(self.service.run(SyncRequest("fake", "items")))

        self.assertEqual(result.records_written, 2)
        self.assertEqual(result.pages_processed, 2)
        self.assertEqual(FakeConnector.requested_cursors, [None, "page-2"])
        records = self.repository.list_records("fake", "items")
        self.assertEqual([item["external_id"] for item in records], ["1", "2"])

    def test_resumes_from_stored_cursor(self) -> None:
        scope = self.service._checkpoint_scope(SyncRequest("fake", "items"))
        self.repository.commit_page("fake", "items", scope, (), "page-2")

        result = asyncio.run(self.service.run(SyncRequest("fake", "items")))

        self.assertEqual(result.resumed_from, "page-2")
        self.assertEqual(FakeConnector.requested_cursors, ["page-2"])

    def test_checkpoint_is_scoped_by_parameters(self) -> None:
        first = SyncRequest("fake", "items", parameters={"state": "SP"})
        first_scope = self.service._checkpoint_scope(first)
        self.repository.commit_page("fake", "items", first_scope, (), "page-2")

        second = SyncRequest("fake", "items", parameters={"state": "MG"})
        result = asyncio.run(self.service.run(second))

        self.assertIsNone(result.resumed_from)
        self.assertEqual(FakeConnector.requested_cursors, [None, "page-2"])

    def test_rejects_unknown_dataset_before_fetch(self) -> None:
        with self.assertRaises(DatasetNotSupportedError):
            asyncio.run(self.service.run(SyncRequest("fake", "unknown")))

    def test_detects_infinite_cursor_loop(self) -> None:
        registry = ConnectorRegistry()
        registry.register(RepeatingCursorConnector)
        service = SyncService(registry, self.repository, object())  # type: ignore[arg-type]
        with self.assertRaises(InvalidResponseError):
            asyncio.run(service.run(SyncRequest("repeat", "items")))


if __name__ == "__main__":
    unittest.main()
