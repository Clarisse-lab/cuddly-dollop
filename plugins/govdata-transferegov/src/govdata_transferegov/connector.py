from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import monotonic
from typing import Any, Mapping
from urllib.parse import urlencode

from govdata.core.errors import (
    ConnectorConfigurationError,
    InvalidResponseError,
    TransportError,
)
from govdata.core.models import ConnectorPage, ConnectorRecord, ConnectorSpec
from govdata.core.ports import HttpClient, HttpResponse, PublicDataConnector


LOGGER = logging.getLogger(__name__)
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


@dataclass(frozen=True, slots=True)
class DatasetDefinition:
    path: str
    id_field: str


DATASETS = {
    "amendment-beneficiaries": DatasetDefinition(
        path="/beneficiario_emenda_parlamentar",
        id_field="id_beneficiario_emenda_parlamentar_programa",
    ),
    "payment-orders": DatasetDefinition(
        path="/ordem-pagamento",
        id_field="id_op",
    ),
}


class TransferegovConnector(PublicDataConnector):
    """Public partnership and federal transfer data from Transferegov."""

    spec = ConnectorSpec(
        id="transferegov",
        display_name="Transferegov - Gestão de Parcerias",
        datasets=tuple(DATASETS),
        version="1",
        source_url="https://api-publica.transferegov.gestao.gov.br",
    )

    def validate_config(self) -> None:
        base_url = self.config.get(
            "base_url",
            "https://api-publica.transferegov.gestao.gov.br/parcerias",
        )
        if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
            raise ConnectorConfigurationError(
                "transferegov.base_url must be an HTTP(S) URL"
            )
        self._base_url = base_url.rstrip("/")

        page_size = self.config.get("page_size", 200)
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= 200
        ):
            raise ConnectorConfigurationError(
                "transferegov.page_size must be between 1 and 200"
            )
        self._page_size = page_size

        timeout = self.config.get("timeout", 60)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or timeout <= 0
        ):
            raise ConnectorConfigurationError(
                "transferegov.timeout must be greater than zero"
            )
        self._timeout = float(timeout)

        requests_per_minute = self.config.get("requests_per_minute", 60)
        if (
            isinstance(requests_per_minute, bool)
            or not isinstance(requests_per_minute, (int, float))
            or requests_per_minute <= 0
        ):
            raise ConnectorConfigurationError(
                "transferegov.requests_per_minute must be greater than zero"
            )
        self._minimum_interval = 60 / float(requests_per_minute)
        self._last_request_at: float | None = None

        retries = self.config.get("transient_retries", 5)
        if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
            raise ConnectorConfigurationError(
                "transferegov.transient_retries must be zero or greater"
            )
        self._transient_retries = retries

    async def fetch_page(
        self,
        dataset: str,
        parameters: Mapping[str, Any],
        cursor: str | None,
        http: HttpClient,
    ) -> ConnectorPage:
        definition = DATASETS.get(dataset)
        if definition is None:
            raise InvalidResponseError(f"unexpected dataset: {dataset}")

        page_number = self._page_number(cursor)
        query = {
            key: value
            for key, value in parameters.items()
            if key not in {"pagina", "tamanho_da_pagina"}
        }
        query["pagina"] = page_number
        query["tamanho_da_pagina"] = self._page_size
        url = f"{self._base_url}{definition.path}?{urlencode(query, doseq=True)}"

        response = await self._get_with_retries(http, url)
        self._raise_for_status(response)
        payload = self._json_object(response)
        items = payload.get("data")
        if not isinstance(items, list):
            raise InvalidResponseError(
                "Transferegov response field 'data' must be a list"
            )

        records = tuple(
            self._record(dataset, definition, item)
            for item in items
        )
        total_pages = self._page_value(payload, "total_pages")
        current_page = self._page_value(payload, "page_number")
        next_cursor = (
            str(current_page + 1)
            if records and current_page < total_pages
            else None
        )
        return ConnectorPage(records=records, next_cursor=next_cursor)

    def _record(
        self,
        dataset: str,
        definition: DatasetDefinition,
        item: Any,
    ) -> ConnectorRecord:
        if not isinstance(item, dict):
            raise InvalidResponseError("Transferegov item must be an object")
        external_id = item.get(definition.id_field)
        if external_id is None or isinstance(external_id, bool):
            raise InvalidResponseError(
                f"Transferegov item is missing '{definition.id_field}'"
            )
        return ConnectorRecord(
            external_id=str(external_id),
            data=item,
            source_url=self._record_url(dataset, definition, external_id),
        )

    def _record_url(
        self,
        dataset: str,
        definition: DatasetDefinition,
        external_id: object,
    ) -> str:
        id_parameter = (
            "id_beneficiario_emenda_parlamentar_programa"
            if dataset == "amendment-beneficiaries"
            else definition.id_field
        )
        query = urlencode(
            {
                id_parameter: external_id,
                "pagina": 1,
                "tamanho_da_pagina": 1,
            }
        )
        return f"{self._base_url}{definition.path}?{query}"

    async def _get_with_retries(
        self,
        http: HttpClient,
        url: str,
    ) -> HttpResponse:
        for attempt in range(self._transient_retries + 1):
            await self._respect_rate_limit()
            response = await http.get(url, timeout=self._timeout)
            self._last_request_at = monotonic()
            if (
                response.status not in TRANSIENT_STATUSES
                or attempt == self._transient_retries
            ):
                return response
            delay = self._retry_delay(response, attempt)
            LOGGER.warning(
                "Transferegov returned HTTP %s; retrying in %.0f seconds (%s/%s)",
                response.status,
                delay,
                attempt + 1,
                self._transient_retries,
            )
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def _respect_rate_limit(self) -> None:
        if self._last_request_at is None:
            return
        remaining = self._minimum_interval - (monotonic() - self._last_request_at)
        if remaining > 0:
            await asyncio.sleep(remaining)

    @staticmethod
    def _retry_delay(response: HttpResponse, attempt: int) -> float:
        retry_after = next(
            (
                value
                for key, value in response.headers.items()
                if key.lower() == "retry-after"
            ),
            None,
        )
        if retry_after is not None:
            try:
                return min(max(float(retry_after), 1), 300)
            except ValueError:
                pass
        return min(10 * (2**attempt), 300)

    @staticmethod
    def _page_number(cursor: str | None) -> int:
        try:
            page_number = int(cursor or "1")
        except ValueError as error:
            raise InvalidResponseError(
                f"invalid Transferegov page cursor: {cursor!r}"
            ) from error
        if page_number < 1:
            raise InvalidResponseError(
                f"invalid Transferegov page cursor: {cursor!r}"
            )
        return page_number

    @staticmethod
    def _page_value(payload: Mapping[str, Any], field: str) -> int:
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise InvalidResponseError(
                f"Transferegov response field '{field}' must be an integer"
            )
        return value

    @staticmethod
    def _raise_for_status(response: HttpResponse) -> None:
        if response.status == 429:
            raise TransportError("Transferegov rate limit exceeded")
        if not 200 <= response.status < 300:
            raise TransportError(
                f"Transferegov returned HTTP {response.status}"
            )

    @staticmethod
    def _json_object(response: HttpResponse) -> dict[str, Any]:
        try:
            payload = response.json()
        except (UnicodeDecodeError, ValueError) as error:
            preview = " ".join(
                response.body[:160].decode("utf-8", errors="replace").split()
            )
            raise InvalidResponseError(
                f"Transferegov returned invalid JSON (body={preview!r})"
            ) from error
        if not isinstance(payload, dict):
            raise InvalidResponseError(
                "Transferegov response must be an object"
            )
        return payload
