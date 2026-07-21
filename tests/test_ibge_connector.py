from __future__ import annotations

import asyncio
import json
import unittest

from govdata.connectors.ibge import IBGEConnector
from govdata.core.errors import ConnectorConfigurationError, InvalidResponseError
from govdata.core.ports import HttpResponse


class FakeHttp:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.response = HttpResponse(status, {}, json.dumps(payload).encode())
        self.urls: list[str] = []

    async def get(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        self.urls.append(url)
        return self.response


class IBGEConnectorTests(unittest.TestCase):
    def test_http_response_accepts_utf8_bom(self) -> None:
        response = HttpResponse(200, {}, b"\xef\xbb\xbf[]")

        self.assertEqual(response.json(), [])

    def test_maps_states_to_connector_records(self) -> None:
        http = FakeHttp([{"id": 35, "sigla": "SP", "nome": "São Paulo"}])

        page = asyncio.run(IBGEConnector().fetch_page("states", {}, None, http))

        self.assertEqual(page.records[0].external_id, "35")
        self.assertIn("/localidades/estados?orderBy=nome", http.urls[0])

    def test_municipalities_requires_state(self) -> None:
        with self.assertRaises(ConnectorConfigurationError):
            asyncio.run(IBGEConnector().fetch_page("municipalities", {}, None, FakeHttp([])))

    def test_rejects_non_list_response(self) -> None:
        with self.assertRaises(InvalidResponseError):
            asyncio.run(IBGEConnector().fetch_page("states", {}, None, FakeHttp({})))

    def test_invalid_json_error_contains_response_diagnostics(self) -> None:
        http = FakeHttp([])
        http.response = HttpResponse(200, {"Content-Type": "text/html"}, b"<html>blocked</html>")

        with self.assertRaisesRegex(InvalidResponseError, "content-type=text/html"):
            asyncio.run(IBGEConnector().fetch_page("states", {}, None, http))


if __name__ == "__main__":
    unittest.main()
