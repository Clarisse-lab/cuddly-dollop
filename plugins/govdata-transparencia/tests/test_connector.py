from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import patch

from govdata.core.errors import (
    ConnectorConfigurationError,
    InvalidResponseError,
    TransportError,
)
from govdata.core.ports import HttpResponse
from govdata_transparencia.connector import PortalTransparenciaConnector


class FakeHttp:
    def __init__(self, payload: object, status: int = 200, headers=None) -> None:  # type: ignore[no-untyped-def]
        self.response = HttpResponse(
            status=status,
            headers=headers or {},
            body=json.dumps(payload).encode(),
        )
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def get(self, url: str, *, headers=None, timeout=30):  # type: ignore[no-untyped-def]
        self.calls.append((url, dict(headers or {})))
        return self.response


class PortalTransparenciaConnectorTests(unittest.TestCase):
    def connector(self, **config):  # type: ignore[no-untyped-def]
        return PortalTransparenciaConnector(
            {"token": "test-token", "requests_per_minute": 100000, **config}
        )

    def test_requires_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                ConnectorConfigurationError, "PORTAL_TRANSPARENCIA_API_KEY"
            ):
                PortalTransparenciaConnector()

    def test_reads_api_key_from_environment(self) -> None:
        with patch.dict(os.environ, {"PORTAL_TRANSPARENCIA_API_KEY": "env-token"}):
            connector = PortalTransparenciaConnector()

        self.assertEqual(connector._token, "env-token")

    def test_fetches_page_with_authentication_and_maps_records(self) -> None:
        http = FakeHttp([{"codigo": "26000", "descricao": "Educação"}])

        page = asyncio.run(
            self.connector().fetch_page("orgaos-siafi", {"descricao": "Educação"}, None, http)
        )

        self.assertEqual(page.records[0].external_id, "26000")
        self.assertEqual(page.next_cursor, "2")
        self.assertIn("descricao=Educa%C3%A7%C3%A3o", http.calls[0][0])
        self.assertIn("pagina=1", http.calls[0][0])
        self.assertEqual(http.calls[0][1]["chave-api-dados"], "test-token")

    def test_empty_page_finishes_pagination(self) -> None:
        page = asyncio.run(
            self.connector().fetch_page("orgaos-siafi", {}, "3", FakeHttp([]))
        )

        self.assertIsNone(page.next_cursor)

    def test_rejects_invalid_cursor(self) -> None:
        with self.assertRaises(InvalidResponseError):
            asyncio.run(
                self.connector().fetch_page("orgaos-siafi", {}, "invalid", FakeHttp([]))
            )

    def test_translates_rejected_key_without_exposing_it(self) -> None:
        with self.assertRaisesRegex(ConnectorConfigurationError, "rejected") as raised:
            asyncio.run(
                self.connector().fetch_page("orgaos-siafi", {}, None, FakeHttp({}, 401))
            )
        self.assertNotIn("test-token", str(raised.exception))

    def test_translates_rate_limit_with_retry_after(self) -> None:
        with self.assertRaisesRegex(TransportError, "retry-after=12"):
            asyncio.run(
                self.connector().fetch_page(
                    "orgaos-siafi", {}, None, FakeHttp({}, 429, {"Retry-After": "12"})
                )
            )

    def test_rejects_item_without_stable_identifier(self) -> None:
        with self.assertRaisesRegex(InvalidResponseError, "codigo"):
            asyncio.run(
                self.connector().fetch_page("orgaos-siafi", {}, None, FakeHttp([{}]))
            )


if __name__ == "__main__":
    unittest.main()
