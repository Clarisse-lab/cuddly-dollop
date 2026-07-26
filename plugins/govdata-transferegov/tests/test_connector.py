from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from govdata.core.errors import (
    ConnectorConfigurationError,
    InvalidResponseError,
    TransportError,
)
from govdata.core.ports import HttpResponse
from govdata_transferegov.connector import TransferegovConnector


class FakeHttpClient:
    def __init__(
        self,
        payload: object,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.response = HttpResponse(
            status=status,
            headers=headers or {"content-type": "application/json"},
            body=json.dumps(payload).encode(),
        )
        self.urls: list[str] = []
        self.timeouts: list[float] = []

    async def get(self, url, *, headers=None, timeout=30):  # type: ignore[no-untyped-def]
        self.urls.append(url)
        self.timeouts.append(timeout)
        return self.response


class SequenceHttpClient(FakeHttpClient):
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.urls = []
        self.timeouts = []

    async def get(self, url, *, headers=None, timeout=30):  # type: ignore[no-untyped-def]
        self.urls.append(url)
        self.timeouts.append(timeout)
        return self.responses.pop(0)


class TransferegovConnectorTests(unittest.TestCase):
    def connector(self, **config):  # type: ignore[no-untyped-def]
        return TransferegovConnector(
            {"requests_per_minute": 100000, **config}
        )

    def test_maps_amendment_beneficiary_and_paginates(self) -> None:
        payload = {
            "data": [
                {
                    "id_beneficiario_emenda_parlamentar_programa": 11983,
                    "nr_cnpj_beneficiario_emenda": "11903220000141",
                    "nm_beneficiario_emenda": "FUNDO MUNICIPAL DE SAUDE",
                    "sg_uf_beneficiario_emenda": "PI",
                    "nr_emenda": "2025.4496.0005",
                    "vl_total_emenda": 300000.0,
                }
            ],
            "total_pages": 2,
            "total_items": 2,
            "page_number": 1,
            "page_size": 1,
        }
        http = FakeHttpClient(payload)

        page = asyncio.run(
            self.connector(page_size=1).fetch_page(
                "amendment-beneficiaries",
                {"aa_emenda": 2025},
                None,
                http,
            )
        )

        self.assertEqual(page.records[0].external_id, "11983")
        self.assertEqual(page.records[0].data["vl_total_emenda"], 300000.0)
        self.assertIn("aa_emenda=2025", http.urls[0])
        self.assertIn("pagina=1", http.urls[0])
        self.assertIn("tamanho_da_pagina=1", http.urls[0])
        self.assertIn(
            "id_beneficiario_emenda_parlamentar_programa=11983",
            page.records[0].source_url or "",
        )
        self.assertEqual(page.next_cursor, "2")

    def test_maps_payment_order_preserving_financial_dates_in_raw_data(self) -> None:
        payload = {
            "data": [
                {
                    "id_op": 276,
                    "nr_ordem_pagamento": "2025OP040959",
                    "in_situacao_op": "Paga",
                    "dt_emissao_op": "2025-08-28T00:00:00",
                    "vl_ordem_pagamento": 600000.0,
                    "nr_ordem_bancaria": "2025OB042579",
                    "dt_emissao_ordem_bancaria": "2025-08-29T00:00:00",
                }
            ],
            "total_pages": 1,
            "total_items": 1,
            "page_number": 1,
            "page_size": 200,
        }

        page = asyncio.run(
            self.connector().fetch_page(
                "payment-orders",
                {},
                None,
                FakeHttpClient(payload),
            )
        )

        self.assertEqual(page.records[0].external_id, "276")
        self.assertEqual(
            page.records[0].data["dt_emissao_ordem_bancaria"],
            "2025-08-29T00:00:00",
        )
        self.assertIsNone(page.records[0].source_updated_at)
        self.assertIsNone(page.next_cursor)

    def test_maps_payment_document_with_confirmed_payee_cnpj(self) -> None:
        payload = {
            "data": [
                {
                    "id_documento_habil": 278,
                    "id_parceria": 18573,
                    "nr_documento_habil": "2025TF845786",
                    "cd_credor_devedor": "11341134000192",
                    "nm_credor_devedor": "FUNDO MUNICIPAL DE SAUDE",
                    "vl_documento_habil": 600000.0,
                    "dt_emissao": "2025-08-28T00:00:00",
                }
            ],
            "total_pages": 1,
            "total_items": 1,
            "page_number": 1,
            "page_size": 200,
        }

        page = asyncio.run(
            self.connector().fetch_page(
                "payment-documents",
                {},
                None,
                FakeHttpClient(payload),
            )
        )

        self.assertEqual(page.records[0].external_id, "278")
        self.assertEqual(
            page.records[0].data["cd_credor_devedor"],
            "11341134000192",
        )
        self.assertIn(
            "id_documento_habil=278",
            page.records[0].source_url or "",
        )

    def test_empty_last_page_finishes_pagination(self) -> None:
        payload = {
            "data": [],
            "total_pages": 3,
            "total_items": 400,
            "page_number": 3,
            "page_size": 200,
        }

        page = asyncio.run(
            self.connector().fetch_page(
                "payment-orders",
                {},
                "3",
                FakeHttpClient(payload),
            )
        )

        self.assertEqual(page.records, ())
        self.assertIsNone(page.next_cursor)

    def test_rejects_item_without_stable_identifier(self) -> None:
        payload = {
            "data": [{}],
            "total_pages": 1,
            "page_number": 1,
        }

        with self.assertRaisesRegex(InvalidResponseError, "id_op"):
            asyncio.run(
                self.connector().fetch_page(
                    "payment-orders",
                    {},
                    None,
                    FakeHttpClient(payload),
                )
            )

    def test_rejects_invalid_pagination_metadata(self) -> None:
        payload = {
            "data": [],
            "total_pages": "1",
            "page_number": 1,
        }

        with self.assertRaisesRegex(InvalidResponseError, "total_pages"):
            asyncio.run(
                self.connector().fetch_page(
                    "payment-orders",
                    {},
                    None,
                    FakeHttpClient(payload),
                )
            )

    def test_rejects_unknown_dataset(self) -> None:
        with self.assertRaisesRegex(InvalidResponseError, "unexpected dataset"):
            asyncio.run(
                self.connector().fetch_page(
                    "missing",
                    {},
                    None,
                    FakeHttpClient({}),
                )
            )

    def test_validates_page_size_and_request_rate(self) -> None:
        with self.assertRaises(ConnectorConfigurationError):
            TransferegovConnector({"page_size": 201})
        with self.assertRaises(ConnectorConfigurationError):
            TransferegovConnector({"requests_per_minute": 0})

    def test_retries_transient_server_error(self) -> None:
        server_error = HttpResponse(status=503, headers={}, body=b"{}")
        success = HttpResponse(
            status=200,
            headers={},
            body=json.dumps(
                {
                    "data": [],
                    "total_pages": 0,
                    "total_items": 0,
                    "page_number": 1,
                    "page_size": 200,
                }
            ).encode(),
        )
        http = SequenceHttpClient([server_error, success])

        with (
            patch(
                "govdata_transferegov.connector.monotonic",
                side_effect=[0.0, 20.0, 20.0],
            ),
            patch(
                "govdata_transferegov.connector.asyncio.sleep",
                new=AsyncMock(),
            ) as sleep,
        ):
            page = asyncio.run(
                self.connector().fetch_page(
                    "payment-orders",
                    {},
                    None,
                    http,
                )
            )

        self.assertEqual(page.records, ())
        self.assertEqual(len(http.urls), 2)
        sleep.assert_awaited_once_with(10)

    def test_fails_after_retry_limit(self) -> None:
        with self.assertRaisesRegex(TransportError, "rate limit"):
            asyncio.run(
                self.connector(transient_retries=0).fetch_page(
                    "payment-orders",
                    {},
                    None,
                    FakeHttpClient({}, status=429),
                )
            )


if __name__ == "__main__":
    unittest.main()
