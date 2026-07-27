from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Mapping
from urllib.parse import quote, urlencode

from govdata.core.errors import (
    ConnectorConfigurationError,
    InvalidResponseError,
    TransportError,
)
from govdata.core.models import ConnectorPage, ConnectorRecord, ConnectorSpec
from govdata.core.ports import HttpClient, HttpResponse, PublicDataConnector


@dataclass(frozen=True, slots=True)
class DatasetDefinition:
    path: str
    id_field: str


DATASETS = {
    "orgaos-siafi": DatasetDefinition(
        path="/api-de-dados/orgaos-siafi",
        id_field="codigo",
    ),
    "emendas": DatasetDefinition(
        path="/api-de-dados/emendas",
        id_field="codigoEmenda",
    ),
    "ceis": DatasetDefinition(
        path="/api-de-dados/ceis",
        id_field="id",
    ),
    "cnep": DatasetDefinition(
        path="/api-de-dados/cnep",
        id_field="id",
    ),
    "cepim": DatasetDefinition(
        path="/api-de-dados/cepim",
        id_field="id",
    ),
}


class PortalTransparenciaConnector(PublicDataConnector):
    """Connector for the Brazilian Federal Transparency Portal API."""

    spec = ConnectorSpec(
        id="transparencia",
        display_name="Portal da Transparência",
        datasets=tuple(DATASETS),
        source_url="https://portaldatransparencia.gov.br",
    )

    def validate_config(self) -> None:
        token = self.config.get("token") or os.getenv("PORTAL_TRANSPARENCIA_API_KEY")
        if not isinstance(token, str) or not token.strip():
            raise ConnectorConfigurationError(
                "set the PORTAL_TRANSPARENCIA_API_KEY environment variable"
            )
        self._token = token.strip()

        base_url = self.config.get(
            "base_url", "https://api.portaldatransparencia.gov.br"
        )
        if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
            raise ConnectorConfigurationError(
                "transparencia.base_url must be an HTTP(S) URL"
            )
        self._base_url = base_url.rstrip("/")

        requests_per_minute = self.config.get("requests_per_minute", 80)
        if (
            isinstance(requests_per_minute, bool)
            or not isinstance(requests_per_minute, (int, float))
            or requests_per_minute <= 0
        ):
            raise ConnectorConfigurationError(
                "transparencia.requests_per_minute must be greater than zero"
            )
        self._minimum_interval = 60 / float(requests_per_minute)
        self._last_request_at: float | None = None

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
        query = {key: value for key, value in parameters.items() if key != "pagina"}
        if dataset == "emendas":
            query.setdefault("ano", datetime.now(UTC).year)
        query["pagina"] = page_number
        url = f"{self._base_url}{definition.path}?{urlencode(query, doseq=True)}"

        await self._respect_rate_limit()
        response = await http.get(
            url,
            headers={"chave-api-dados": self._token},
        )
        self._last_request_at = monotonic()
        self._raise_for_status(response)
        payload = self._json_list(response)

        records: list[ConnectorRecord] = []
        for item in payload:
            if not isinstance(item, dict) or definition.id_field not in item:
                raise InvalidResponseError(
                    f"Portal item is missing '{definition.id_field}'"
                )
            records.append(
                ConnectorRecord(
                    external_id=str(item[definition.id_field]),
                    data=item,
                    source_url=self._source_url(dataset, item, url),
                )
            )
        return ConnectorPage(
            records=tuple(records),
            next_cursor=str(page_number + 1) if records else None,
        )

    @staticmethod
    def _source_url(dataset: str, item: Mapping[str, Any], fallback: str) -> str:
        if dataset == "emendas":
            code = item.get("codigoEmenda")
            if code is not None:
                return (
                    "https://portaldatransparencia.gov.br/emendas/detalhe"
                    f"?codigoEmenda={quote(str(code), safe='')}"
                )
        if dataset in {"ceis", "cnep", "cepim"}:
            cnpj = PortalTransparenciaConnector._sanctioned_cnpj(dataset, item)
            if cnpj:
                return (
                    "https://portaldatransparencia.gov.br/sancoes/consulta?"
                    f"{urlencode({'cpfCnpj': cnpj})}"
                )
        return fallback

    @staticmethod
    def _sanctioned_cnpj(dataset: str, item: Mapping[str, Any]) -> str | None:
        container_name = "pessoaJuridica" if dataset == "cepim" else "sancionado"
        container = item.get(container_name)
        if not isinstance(container, Mapping):
            return None
        field = "cnpjFormatado" if dataset == "cepim" else "codigoFormatado"
        digits = "".join(
            character for character in str(container.get(field, "")) if character.isdigit()
        )
        return digits if len(digits) == 14 else None

    async def _respect_rate_limit(self) -> None:
        if self._last_request_at is None:
            return
        remaining = self._minimum_interval - (monotonic() - self._last_request_at)
        if remaining > 0:
            await asyncio.sleep(remaining)

    @staticmethod
    def _page_number(cursor: str | None) -> int:
        try:
            page_number = int(cursor or "1")
        except ValueError as error:
            raise InvalidResponseError(f"invalid page cursor: {cursor!r}") from error
        if page_number < 1:
            raise InvalidResponseError(f"invalid page cursor: {cursor!r}")
        return page_number

    @staticmethod
    def _raise_for_status(response: HttpResponse) -> None:
        if response.status in {401, 403}:
            raise ConnectorConfigurationError(
                "Portal da Transparência rejected the API key"
            )
        if response.status == 429:
            retry_after = next(
                (
                    value
                    for key, value in response.headers.items()
                    if key.lower() == "retry-after"
                ),
                "unknown",
            )
            raise TransportError(
                f"Portal da Transparência rate limit exceeded; retry-after={retry_after}"
            )
        if not 200 <= response.status < 300:
            raise TransportError(
                f"Portal da Transparência returned HTTP {response.status}"
            )

    @staticmethod
    def _json_list(response: HttpResponse) -> list[Any]:
        try:
            payload = response.json()
        except (UnicodeDecodeError, ValueError) as error:
            content_type = next(
                (
                    value
                    for key, value in response.headers.items()
                    if key.lower() == "content-type"
                ),
                "unknown",
            )
            preview = " ".join(
                response.body[:160].decode("utf-8", errors="replace").split()
            )
            raise InvalidResponseError(
                "Portal da Transparência returned invalid JSON "
                f"(content-type={content_type}; body={preview!r})"
            ) from error
        if not isinstance(payload, list):
            raise InvalidResponseError("Portal response must be a list")
        return payload
