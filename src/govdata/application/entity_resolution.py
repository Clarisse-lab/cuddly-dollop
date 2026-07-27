from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from govdata.core.entities import EntityRecordReferences, EntityReference
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


@dataclass(frozen=True, slots=True)
class ReferenceJoinRule:
    connector_id: str
    reference_dataset: str
    target_dataset: str
    target_reference_field: str
    reference_extractor: ExtractorFn


REFERENCE_JOIN_RULES = (
    ReferenceJoinRule(
        connector_id="transferegov",
        reference_dataset="payment-documents",
        target_dataset="payment-orders",
        target_reference_field="id_documento_habil",
        reference_extractor=_transferegov_payment_documents,
    ),
)


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
                batch: list[EntityRecordReferences] = []
                for record in page.records:
                    refs = extractor(record.data)
                    if refs:
                        batch.append(
                            EntityRecordReferences(
                                external_id=record.external_id,
                                references=refs,
                            )
                        )
                        links_written += len(refs)
                    records_processed += 1
                if batch:
                    self._repository.record_entity_links_batch(
                        connector_id,
                        dataset,
                        tuple(batch),
                        observed_at,
                    )
                offset += len(page.records)
                if offset >= page.total:
                    break

        for rule in REFERENCE_JOIN_RULES:
            reference_map = self._load_reference_map(rule, batch_size)
            offset = 0
            while True:
                page = self._repository.query_records(
                    rule.connector_id,
                    rule.target_dataset,
                    limit=batch_size,
                    offset=offset,
                )
                if not page.records:
                    break
                batch: list[EntityRecordReferences] = []
                for record in page.records:
                    reference_value = record.data.get(rule.target_reference_field)
                    reference_id = self._reference_id(reference_value)
                    refs = reference_map.get(reference_id, ()) if reference_id else ()
                    if refs:
                        batch.append(
                            EntityRecordReferences(
                                external_id=record.external_id,
                                references=refs,
                            )
                        )
                        links_written += len(refs)
                    records_processed += 1
                if batch:
                    self._repository.record_entity_links_batch(
                        rule.connector_id,
                        rule.target_dataset,
                        tuple(batch),
                        observed_at,
                    )
                offset += len(page.records)
                if offset >= page.total:
                    break

        return {"records_processed": records_processed, "links_written": links_written}

    def _load_reference_map(
        self,
        rule: ReferenceJoinRule,
        batch_size: int,
    ) -> dict[str, tuple[EntityReference, ...]]:
        references: dict[str, tuple[EntityReference, ...]] = {}
        offset = 0
        while True:
            page = self._repository.query_records(
                rule.connector_id,
                rule.reference_dataset,
                limit=batch_size,
                offset=offset,
            )
            if not page.records:
                break
            for record in page.records:
                refs = rule.reference_extractor(record.data)
                if refs:
                    references[record.external_id] = refs
            offset += len(page.records)
            if offset >= page.total:
                break
        return references

    @staticmethod
    def _reference_id(value: Any) -> str | None:
        if value is None or isinstance(value, bool):
            return None
        return str(value)
