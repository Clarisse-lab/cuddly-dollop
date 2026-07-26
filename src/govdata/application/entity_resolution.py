from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from govdata.core.entities import EntityReference
from govdata.core.ports import DataRepository

ExtractorFn = Callable[[Mapping[str, Any]], tuple[EntityReference, ...]]

_DEFAULT_BATCH_SIZE = 500


def _cnpj(value: Any) -> str | None:
    digits = "".join(character for character in str(value) if character.isdigit())
    return digits if len(digits) == 14 else None


def _uf(value: Any) -> str | None:
    text = str(value).strip().upper() if value is not None else ""
    return text if len(text) == 2 and text.isalpha() else None


def _pncp_open_opportunities(data: Mapping[str, Any]) -> tuple[EntityReference, ...]:
    refs: list[EntityReference] = []
    organization = data.get("orgaoEntidade")
    if isinstance(organization, dict):
        cnpj = _cnpj(organization.get("cnpj"))
        if cnpj:
            refs.append(
                EntityReference(
                    "organization", cnpj, organization.get("razaoSocial"), role="buyer"
                )
            )
    # unidadeOrgao.ufSigla is not covered by the connector's own tests (only observed
    # in frontend/app.js), so this extraction is best-effort and silently skipped when
    # the field is absent or shaped differently than expected.
    unit = data.get("unidadeOrgao")
    if isinstance(unit, dict):
        uf = _uf(unit.get("ufSigla"))
        if uf:
            refs.append(EntityReference("location", uf, role="buyer-location"))
    return tuple(refs)


def _transferegov_amendment_beneficiaries(data: Mapping[str, Any]) -> tuple[EntityReference, ...]:
    refs: list[EntityReference] = []
    cnpj = _cnpj(data.get("nr_cnpj_beneficiario_emenda"))
    if cnpj:
        refs.append(
            EntityReference(
                "organization",
                cnpj,
                data.get("nm_beneficiario_emenda"),
                role="beneficiary",
            )
        )
    uf = _uf(data.get("sg_uf_beneficiario_emenda"))
    if uf:
        refs.append(EntityReference("location", uf, role="beneficiary-location"))
    return tuple(refs)


def _transferegov_payment_documents(
    data: Mapping[str, Any],
) -> tuple[EntityReference, ...]:
    cnpj = _cnpj(data.get("cd_credor_devedor"))
    if not cnpj:
        return ()
    return (
        EntityReference(
            "organization",
            cnpj,
            data.get("nm_credor_devedor"),
            role="payee",
        ),
    )


EXTRACTORS: dict[tuple[str, str], ExtractorFn] = {
    ("pncp", "open-opportunities"): _pncp_open_opportunities,
    ("transferegov", "amendment-beneficiaries"): _transferegov_amendment_beneficiaries,
    ("transferegov", "payment-documents"): _transferegov_payment_documents,
}


class EntityResolutionService:
    def __init__(self, repository: DataRepository) -> None:
        self._repository = repository

    def run(self, *, batch_size: int = _DEFAULT_BATCH_SIZE) -> dict[str, int]:
        records_processed = 0
        links_written = 0
        observed_at = datetime.now(UTC)

        for (connector_id, dataset), extractor in EXTRACTORS.items():
            offset = 0
            while True:
                page = self._repository.query_records(
                    connector_id, dataset, limit=batch_size, offset=offset
                )
                if not page.records:
                    break
                for record in page.records:
                    refs = extractor(record.data)
                    if refs:
                        self._repository.record_entity_links(
                            connector_id, dataset, record.external_id, refs, observed_at
                        )
                        links_written += len(refs)
                    records_processed += 1
                offset += len(page.records)
                if offset >= page.total:
                    break

        return {"records_processed": records_processed, "links_written": links_written}
