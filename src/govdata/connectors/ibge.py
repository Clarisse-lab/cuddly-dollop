from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import quote, urlencode

from govdata.core.errors import ConnectorConfigurationError, InvalidResponseError
from govdata.core.models import ConnectorPage, ConnectorRecord, ConnectorSpec
from govdata.core.ports import HttpClient, PublicDataConnector


class IBGEConnector(PublicDataConnector):
    spec = ConnectorSpec(
        id="ibge",
        display_name="IBGE Localidades",
        datasets=("states", "municipalities"),
        source_url="https://servicodados.ibge.gov.br",
    )

    def validate_config(self) -> None:
        base_url = self.config.get("base_url", "https://servicodados.ibge.gov.br")
        if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
            raise ConnectorConfigurationError("ibge.base_url must be an HTTP(S) URL")

    async def fetch_page(
        self,
        dataset: str,
        parameters: Mapping[str, Any],
        cursor: str | None,
        http: HttpClient,
    ) -> ConnectorPage:
        if cursor is not None:
            return ConnectorPage(records=())

        base_url = str(
            self.config.get("base_url", "https://servicodados.ibge.gov.br")
        ).rstrip("/")
        if dataset == "states":
            path = "/api/v1/localidades/estados"
        elif dataset == "municipalities":
            state = parameters.get("state")
            if not state:
                raise ConnectorConfigurationError(
                    "parameter 'state' is required for municipalities"
                )
            path = f"/api/v1/localidades/estados/{quote(str(state), safe='')}/municipios"
        else:
            raise InvalidResponseError(f"unexpected dataset: {dataset}")

        response = await http.get(f"{base_url}{path}?{urlencode({'orderBy': 'nome'})}")
        if not 200 <= response.status < 300:
            raise InvalidResponseError(f"IBGE returned HTTP {response.status}")
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
            preview = response.body[:160].decode("utf-8", errors="replace")
            preview = " ".join(preview.split())
            raise InvalidResponseError(
                f"IBGE returned invalid JSON (content-type={content_type}; body={preview!r})"
            ) from error
        if not isinstance(payload, list):
            raise InvalidResponseError("IBGE response must be a list")

        records: list[ConnectorRecord] = []
        for item in payload:
            if not isinstance(item, dict) or "id" not in item:
                raise InvalidResponseError("IBGE item is missing an id")
            records.append(
                ConnectorRecord(
                    external_id=str(item["id"]),
                    data=item,
                    source_url=f"{base_url}{path}",
                )
            )
        return ConnectorPage(records=tuple(records))
