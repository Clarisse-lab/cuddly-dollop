from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping
from urllib.parse import urlencode

from govdata.core.errors import (
    ConnectorConfigurationError,
    InvalidResponseError,
    TransportError,
)
from govdata.core.models import ConnectorPage, ConnectorRecord, ConnectorSpec
from govdata.core.ports import HttpClient, HttpResponse, PublicDataConnector


class PNCPConnector(PublicDataConnector):
    """Open procurement opportunities from Brazil's official PNCP API."""

    spec = ConnectorSpec(
        id="pncp",
        display_name="Portal Nacional de Contratações Públicas",
        datasets=("open-opportunities",),
        source_url="https://pncp.gov.br",
    )

    def validate_config(self) -> None:
        base_url = self.config.get("base_url", "https://pncp.gov.br/api/consulta")
        if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
            raise ConnectorConfigurationError("pncp.base_url must be an HTTP(S) URL")
        self._base_url = base_url.rstrip("/")

        page_size = self.config.get("page_size", 50)
        if isinstance(page_size, bool) or not isinstance(page_size, int) or not 10 <= page_size <= 50:
            raise ConnectorConfigurationError("pncp.page_size must be between 10 and 50")
        self._page_size = page_size

        timeout = self.config.get("timeout", 60)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or timeout <= 0
        ):
            raise ConnectorConfigurationError("pncp.timeout must be greater than zero")
        self._timeout = float(timeout)

    async def fetch_page(
        self,
        dataset: str,
        parameters: Mapping[str, Any],
        cursor: str | None,
        http: HttpClient,
    ) -> ConnectorPage:
        if dataset != "open-opportunities":
            raise InvalidResponseError(f"unexpected dataset: {dataset}")

        page_number = self._page_number(cursor)
        query = {
            key: value
            for key, value in parameters.items()
            if key not in {"pagina", "tamanhoPagina"}
        }
        data_final = str(query.get("dataFinal") or datetime.now(UTC).strftime("%Y%m%d"))
        if len(data_final) != 8 or not data_final.isdigit():
            raise ConnectorConfigurationError(
                "pncp parameter 'dataFinal' must use YYYYMMDD"
            )
        query["dataFinal"] = data_final
        query["pagina"] = page_number
        query["tamanhoPagina"] = self._page_size
        url = f"{self._base_url}/v1/contratacoes/proposta?{urlencode(query, doseq=True)}"

        response = await http.get(url, timeout=self._timeout)
        self._raise_for_status(response)
        payload = self._json_object(response)
        items = payload.get("data")
        if not isinstance(items, list):
            raise InvalidResponseError("PNCP response field 'data' must be a list")

        records: list[ConnectorRecord] = []
        for item in items:
            if not isinstance(item, dict):
                raise InvalidResponseError("PNCP opportunity must be an object")
            external_id = item.get("numeroControlePNCP")
            if not isinstance(external_id, str) or not external_id:
                raise InvalidResponseError(
                    "PNCP opportunity is missing 'numeroControlePNCP'"
                )
            records.append(
                ConnectorRecord(
                    external_id=external_id,
                    data=item,
                    source_updated_at=self._source_updated_at(item),
                    source_url=self._opportunity_url(item, url),
                )
            )

        total_pages = payload.get("totalPaginas")
        current_page = payload.get("numeroPagina", page_number)
        if (
            isinstance(total_pages, bool)
            or not isinstance(total_pages, int)
            or isinstance(current_page, bool)
            or not isinstance(current_page, int)
        ):
            raise InvalidResponseError("PNCP response has invalid pagination metadata")
        next_cursor = (
            str(current_page + 1)
            if items and current_page < total_pages
            else None
        )
        return ConnectorPage(records=tuple(records), next_cursor=next_cursor)

    @staticmethod
    def _page_number(cursor: str | None) -> int:
        try:
            page_number = int(cursor or "1")
        except ValueError as error:
            raise InvalidResponseError(f"invalid PNCP page cursor: {cursor!r}") from error
        if page_number < 1:
            raise InvalidResponseError(f"invalid PNCP page cursor: {cursor!r}")
        return page_number

    @staticmethod
    def _source_updated_at(item: Mapping[str, Any]) -> datetime | None:
        raw = item.get("dataAtualizacaoGlobal") or item.get("dataAtualizacao")
        if not isinstance(raw, str) or not raw:
            return None
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as error:
            raise InvalidResponseError("PNCP returned an invalid update timestamp") from error
        return value.replace(tzinfo=value.tzinfo or UTC)

    @staticmethod
    def _opportunity_url(item: Mapping[str, Any], fallback: str) -> str:
        organization = item.get("orgaoEntidade")
        cnpj = organization.get("cnpj") if isinstance(organization, dict) else None
        year = item.get("anoCompra")
        sequence = item.get("sequencialCompra")
        if cnpj and year is not None and sequence is not None:
            return f"https://pncp.gov.br/app/editais/{cnpj}/{year}/{sequence}"
        return fallback

    @staticmethod
    def _raise_for_status(response: HttpResponse) -> None:
        if response.status == 429:
            raise TransportError("PNCP rate limit exceeded")
        if not 200 <= response.status < 300:
            raise TransportError(f"PNCP returned HTTP {response.status}")

    @staticmethod
    def _json_object(response: HttpResponse) -> dict[str, Any]:
        try:
            payload = response.json()
        except (UnicodeDecodeError, ValueError) as error:
            preview = " ".join(
                response.body[:160].decode("utf-8", errors="replace").split()
            )
            raise InvalidResponseError(
                f"PNCP returned invalid JSON (body={preview!r})"
            ) from error
        if not isinstance(payload, dict):
            raise InvalidResponseError("PNCP response must be an object")
        return payload
