from __future__ import annotations

import asyncio
import io
import unittest
from email.message import Message
from urllib.error import HTTPError
from unittest.mock import patch

from govdata.infrastructure.http import UrllibHttpClient


class HttpClientTests(unittest.TestCase):
    def test_returns_http_error_as_response_for_connector_handling(self) -> None:
        headers = Message()
        headers["Content-Type"] = "application/json"
        error = HTTPError(
            "https://example.gov.br",
            401,
            "Unauthorized",
            headers,
            io.BytesIO(b'{"error":"unauthorized"}'),
        )

        with patch("govdata.infrastructure.http.urlopen", side_effect=error):
            response = asyncio.run(UrllibHttpClient(retries=0).get("https://example.gov.br"))

        self.assertEqual(response.status, 401)
        self.assertEqual(response.json(), {"error": "unauthorized"})

    def test_retries_rate_limit_and_honors_retry_after(self) -> None:
        limited = type(
            "Response",
            (),
            {"status": 429, "headers": {"Retry-After": "0"}, "body": b"{}"},
        )()
        success = type(
            "Response",
            (),
            {"status": 200, "headers": {}, "body": b"[]"},
        )()
        client = UrllibHttpClient(retries=1)

        with patch.object(client, "_get_sync", side_effect=[limited, success]) as get_sync:
            response = asyncio.run(client.get("https://example.gov.br"))

        self.assertEqual(response.status, 200)
        self.assertEqual(get_sync.call_count, 2)


if __name__ == "__main__":
    unittest.main()
