from __future__ import annotations

import asyncio
import gzip
import zlib
from collections.abc import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from govdata.core.errors import TransportError
from govdata.core.ports import HttpResponse


class UrllibHttpClient:
    def __init__(self, retries: int = 2, user_agent: str = "govdata-platform/0.1") -> None:
        self._retries = retries
        self._user_agent = user_agent

    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30,
    ) -> HttpResponse:
        request_headers = {"Accept": "application/json", "User-Agent": self._user_agent}
        request_headers.update(headers or {})
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                return await asyncio.to_thread(
                    self._get_sync, url, request_headers, timeout
                )
            except (HTTPError, URLError, TimeoutError) as error:
                last_error = error
                if attempt < self._retries:
                    await asyncio.sleep(0.25 * (2**attempt))
        raise TransportError(f"GET {url} failed: {last_error}") from last_error

    @staticmethod
    def _get_sync(url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse:
        request = Request(url, headers=dict(headers), method="GET")
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read()
            content_encoding = response.headers.get("Content-Encoding", "").lower()
            if content_encoding == "gzip":
                body = gzip.decompress(body)
            elif content_encoding == "deflate":
                body = zlib.decompress(body)
            return HttpResponse(
                status=response.status,
                headers=dict(response.headers.items()),
                body=body,
            )
