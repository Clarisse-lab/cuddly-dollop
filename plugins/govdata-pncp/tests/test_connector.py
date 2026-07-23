from __future__ import annotations

import asyncio
import json
import unittest
from datetime import UTC, datetime

from govdata.core.errors import ConnectorConfigurationError, InvalidResponseError
from govdata.core.ports import HttpResponse
from govdata_pncp.connector import PNCPConnector


class FakeHttpClient:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.response = HttpResponse(
            status=status,
            headers={"content-type": "application/json"},
            body=json.dumps(payload).encode(),
        )
        self.urls: list[str] = []
        self.timeouts: list[float] = []

    async def get(self, url, *, headers=None, timeout=30):  # type: ignore[no-untyped-def]
        self.urls.append(url)
        self.timeouts.append(timeout)
        return self.response


class PNCPConnectorTests(unittest.TestCase):
    def test_fetches_and_maps_open_opportunities(self) -> None:
        payload = {
            "data": [
                {
                    "numeroControlePNCP": "12345678000100-1-000001/2026",
                    "anoCompra": 2026,
                    "sequencialCompra": 1,
                    "dataAtualizacaoGlobal": "2026-07-22T18:06:39",
                    "orgaoEntidade": {"cnpj": "12345678000100"},
                    "objetoCompra": "Aquisição de equipamentos",
                }
            ],
            "totalPaginas": 2,
            "numeroPagina": 1,
        }
        http = FakeHttpClient(payload)

        page = asyncio.run(
            PNCPConnector().fetch_page(
                "open-opportunities",
                {"dataFinal": "20260722", "uf": "SP"},
                None,
                http,
            )
        )

        self.assertEqual(page.records[0].external_id, "12345678000100-1-000001/2026")
        self.assertEqual(
            page.records[0].source_url,
            "https://pncp.gov.br/app/editais/12345678000100/2026/1",
        )
        self.assertEqual(
            page.records[0].source_updated_at,
            datetime(2026, 7, 22, 18, 6, 39, tzinfo=UTC),
        )
        self.assertEqual(page.next_cursor, "2")
        self.assertIn("dataFinal=20260722", http.urls[0])
        self.assertIn("uf=SP", http.urls[0])
        self.assertIn("tamanhoPagina=50", http.urls[0])
        self.assertEqual(http.timeouts, [60.0])

    def test_last_page_finishes_pagination(self) -> None:
        http = FakeHttpClient(
            {"data": [], "totalPaginas": 1, "numeroPagina": 1}
        )

        page = asyncio.run(
            PNCPConnector().fetch_page("open-opportunities", {}, None, http)
        )

        self.assertEqual(page.records, ())
        self.assertIsNone(page.next_cursor)

    def test_rejects_invalid_date(self) -> None:
        with self.assertRaises(ConnectorConfigurationError):
            asyncio.run(
                PNCPConnector().fetch_page(
                    "open-opportunities",
                    {"dataFinal": "22/07/2026"},
                    None,
                    FakeHttpClient({}),
                )
            )

    def test_rejects_invalid_pagination_shape(self) -> None:
        with self.assertRaises(InvalidResponseError):
            asyncio.run(
                PNCPConnector().fetch_page(
                    "open-opportunities",
                    {"dataFinal": "20260722"},
                    None,
                    FakeHttpClient({"data": [], "totalPaginas": "1"}),
                )
            )

    def test_validates_page_size(self) -> None:
        with self.assertRaises(ConnectorConfigurationError):
            PNCPConnector({"page_size": 2})


if __name__ == "__main__":
    unittest.main()
