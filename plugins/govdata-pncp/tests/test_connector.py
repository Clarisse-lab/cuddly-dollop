from __future__ import annotations

import asyncio
import json
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from govdata.core.errors import (
    ConnectorConfigurationError,
    InvalidResponseError,
    TransportError,
)
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


class SequenceHttpClient(FakeHttpClient):
    def __init__(self, responses: list[HttpResponse | TransportError]) -> None:
        self.responses = responses
        self.urls = []
        self.timeouts = []

    async def get(self, url, *, headers=None, timeout=30):  # type: ignore[no-untyped-def]
        self.urls.append(url)
        self.timeouts.append(timeout)
        response = self.responses.pop(0)
        if isinstance(response, TransportError):
            raise response
        return response


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

    def test_fetches_and_maps_contracts(self) -> None:
        payload = {
            "data": [
                {
                    "numeroControlePNCP": "12345678000100-2-000007/2026",
                    "sequencialContrato": 7,
                    "anoContrato": 2026,
                    "dataAtualizacao": "2026-07-27T18:06:39",
                    "orgaoEntidade": {"cnpj": "12345678000100"},
                    "niFornecedor": "00987654000199",
                    "objetoContrato": "Serviços de manutenção",
                    "valorGlobal": 250000,
                }
            ],
            "totalPaginas": 1,
            "numeroPagina": 1,
        }
        http = FakeHttpClient(payload)

        page = asyncio.run(
            PNCPConnector().fetch_page(
                "contracts",
                {"dataInicial": "20260701", "dataFinal": "20260727"},
                None,
                http,
            )
        )

        self.assertEqual(page.records[0].external_id, "12345678000100-2-000007/2026")
        self.assertEqual(
            page.records[0].source_url,
            "https://pncp.gov.br/app/contratos/12345678000100/2026/7",
        )
        self.assertEqual(
            page.records[0].source_updated_at,
            datetime(2026, 7, 27, 18, 6, 39, tzinfo=UTC),
        )
        self.assertIn("/v1/contratos/atualizacao?", http.urls[0])
        self.assertIn("dataInicial=20260701", http.urls[0])
        self.assertIn("dataFinal=20260727", http.urls[0])

    def test_contracts_default_to_previous_utc_day(self) -> None:
        http = FakeHttpClient(
            {"data": [], "totalPaginas": 1, "numeroPagina": 1}
        )

        with patch("govdata_pncp.connector.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = datetime(2026, 7, 28, 2, tzinfo=UTC)
            asyncio.run(PNCPConnector().fetch_page("contracts", {}, None, http))

        self.assertIn("dataInicial=20260727", http.urls[0])
        self.assertIn("dataFinal=20260727", http.urls[0])

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

    def test_rejects_invalid_contract_initial_date(self) -> None:
        with self.assertRaises(ConnectorConfigurationError):
            asyncio.run(
                PNCPConnector().fetch_page(
                    "contracts",
                    {"dataInicial": "01/07/2026", "dataFinal": "20260722"},
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

    def test_waits_and_retries_rate_limit(self) -> None:
        limited = HttpResponse(
            status=429,
            headers={"Retry-After": "7"},
            body=b"{}",
        )
        success = HttpResponse(
            status=200,
            headers={},
            body=json.dumps(
                {"data": [], "totalPaginas": 1, "numeroPagina": 1}
            ).encode(),
        )
        http = SequenceHttpClient([limited, success])

        with (
            patch(
                "govdata_pncp.connector.monotonic",
                side_effect=[0.0, 10.0, 10.0],
            ),
            patch(
                "govdata_pncp.connector.asyncio.sleep",
                new=AsyncMock(),
            ) as sleep,
        ):
            page = asyncio.run(
                PNCPConnector().fetch_page(
                    "open-opportunities",
                    {"dataFinal": "20260723"},
                    None,
                    http,
                )
            )

        self.assertEqual(page.records, ())
        self.assertEqual(len(http.urls), 2)
        sleep.assert_awaited_once_with(7.0)

    def test_fails_after_configured_rate_limit_retries(self) -> None:
        http = FakeHttpClient({}, status=429)

        with self.assertRaisesRegex(TransportError, "rate limit"):
            asyncio.run(
                PNCPConnector({"rate_limit_retries": 0}).fetch_page(
                    "open-opportunities",
                    {"dataFinal": "20260723"},
                    None,
                    http,
                )
            )

    def test_waits_and_recovers_from_server_error(self) -> None:
        server_error = HttpResponse(status=500, headers={}, body=b"{}")
        success = HttpResponse(
            status=200,
            headers={},
            body=json.dumps(
                {"data": [], "totalPaginas": 1, "numeroPagina": 1}
            ).encode(),
        )
        http = SequenceHttpClient([server_error, success])

        with (
            patch(
                "govdata_pncp.connector.monotonic",
                side_effect=[0.0, 20.0, 20.0],
            ),
            patch(
                "govdata_pncp.connector.asyncio.sleep",
                new=AsyncMock(),
            ) as sleep,
            self.assertLogs("govdata_pncp.connector", level="WARNING") as logs,
        ):
            page = asyncio.run(
                PNCPConnector().fetch_page(
                    "open-opportunities",
                    {"dataFinal": "20260723"},
                    None,
                    http,
                )
            )

        self.assertEqual(page.records, ())
        self.assertEqual(len(http.urls), 2)
        sleep.assert_awaited_once_with(15)
        self.assertIn("HTTP 500", logs.output[0])

    def test_waits_and_recovers_from_transport_error(self) -> None:
        timeout = TransportError("PNCP request timed out")
        success = HttpResponse(
            status=200,
            headers={},
            body=json.dumps(
                {"data": [], "totalPaginas": 1, "numeroPagina": 1}
            ).encode(),
        )
        http = SequenceHttpClient([timeout, success])

        with (
            patch(
                "govdata_pncp.connector.monotonic",
                side_effect=[0.0, 20.0, 20.0],
            ),
            patch(
                "govdata_pncp.connector.asyncio.sleep",
                new=AsyncMock(),
            ) as sleep,
            self.assertLogs("govdata_pncp.connector", level="WARNING") as logs,
        ):
            page = asyncio.run(
                PNCPConnector().fetch_page(
                    "open-opportunities",
                    {"dataFinal": "20260723"},
                    None,
                    http,
                )
            )

        self.assertEqual(page.records, ())
        self.assertEqual(len(http.urls), 2)
        sleep.assert_awaited_once_with(15)
        self.assertIn("failed temporarily", logs.output[0])

    def test_raises_transport_error_after_configured_retries(self) -> None:
        timeout = TransportError("PNCP request timed out")
        http = SequenceHttpClient([timeout])

        with self.assertRaisesRegex(TransportError, "timed out"):
            asyncio.run(
                PNCPConnector({"rate_limit_retries": 0}).fetch_page(
                    "open-opportunities",
                    {"dataFinal": "20260723"},
                    None,
                    http,
                )
            )

        self.assertEqual(len(http.urls), 1)

    def test_validates_request_rate(self) -> None:
        with self.assertRaises(ConnectorConfigurationError):
            PNCPConnector({"requests_per_minute": 0})


if __name__ == "__main__":
    unittest.main()
