from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from govdata.api.app import ApiSettings, create_app
from govdata.connectors.ibge import IBGEConnector
from govdata.core.entities import EntityReference
from govdata.core.models import StoredRecord
from govdata.core.registry import ConnectorRegistry
from govdata.infrastructure.sqlite import SQLiteRecordRepository


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "api.sqlite3"
        self.repository = SQLiteRecordRepository(self.database)
        self.registry = ConnectorRegistry()
        self.registry.register(IBGEConnector)
        self.repository.commit_page(
            "ibge",
            "states",
            "test-scope",
            (
                StoredRecord(
                    connector_id="ibge",
                    dataset="states",
                    external_id="35",
                    data={"id": 35, "sigla": "SP", "nome": "São Paulo"},
                    collected_at=datetime(2026, 7, 21, tzinfo=UTC),
                ),
                StoredRecord(
                    connector_id="ibge",
                    dataset="states",
                    external_id="33",
                    data={"id": 33, "sigla": "RJ", "nome": "Rio de Janeiro"},
                    collected_at=datetime(2026, 7, 21, tzinfo=UTC),
                ),
            ),
            None,
        )
        app = create_app(
            settings=ApiSettings(self.database, ("https://dashboard.example",)),
            registry=self.registry,
            repository=self.repository,
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_health(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_lists_connectors(self) -> None:
        response = self.client.get("/api/v1/connectors")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["id"], "ibge")
        self.assertEqual(
            response.json()[0]["source_url"],
            "https://servicodados.ibge.gov.br",
        )

    def test_returns_paginated_records(self) -> None:
        response = self.client.get("/api/v1/records/ibge/states?limit=1&offset=1")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["limit"], 1)
        self.assertEqual(body["offset"], 1)
        self.assertEqual(body["items"][0]["external_id"], "35")
        self.assertTrue(body["items"][0]["content_hash"])

    def test_rejects_unknown_connector(self) -> None:
        response = self.client.get("/api/v1/records/missing/states")

        self.assertEqual(response.status_code, 404)

    def test_validates_pagination(self) -> None:
        response = self.client.get("/api/v1/records/ibge/states?limit=1000")

        self.assertEqual(response.status_code, 422)

    def test_returns_entity_profile_with_links(self) -> None:
        self.repository.record_entity_links(
            "pncp",
            "open-opportunities",
            "1",
            (EntityReference("organization", "12345678000100", "Prefeitura", role="buyer"),),
            datetime(2026, 7, 25, tzinfo=UTC),
        )

        response = self.client.get("/api/v1/entities/organization/12345678000100")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["display_name"], "Prefeitura")
        self.assertEqual(body["links"][0]["connector_id"], "pncp")
        self.assertEqual(body["links"][0]["role"], "buyer")

    def test_returns_404_for_unknown_entity(self) -> None:
        response = self.client.get("/api/v1/entities/organization/00000000000000")

        self.assertEqual(response.status_code, 404)

    def test_cors_allows_configured_frontend(self) -> None:
        response = self.client.options(
            "/api/v1/connectors",
            headers={
                "Origin": "https://dashboard.example",
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"],
            "https://dashboard.example",
        )


class ApiSettingsTests(unittest.TestCase):
    def test_keeps_local_origins_alongside_deployed_frontend(self) -> None:
        with patch.dict(
            "os.environ",
            {"GOVDATA_CORS_ORIGINS": "https://dashboard.example"},
            clear=True,
        ):
            settings = ApiSettings.from_environment()

        self.assertIn("http://localhost:5173", settings.cors_origins)
        self.assertIn("http://127.0.0.1:5173", settings.cors_origins)
        self.assertIn("https://dashboard.example", settings.cors_origins)


if __name__ == "__main__":
    unittest.main()
