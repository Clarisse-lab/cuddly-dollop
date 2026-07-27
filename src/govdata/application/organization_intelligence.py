from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping

from govdata.core.entities import EntityLinkedRecord
from govdata.core.intelligence import OrganizationActivity, OrganizationOverview
from govdata.core.ports import DataRepository


class OrganizationIntelligenceService:
    def __init__(self, repository: DataRepository) -> None:
        self._repository = repository

    def get(self, cnpj: str) -> OrganizationOverview | None:
        profile = self._repository.get_entity_profile("organization", cnpj)
        if profile is None:
            return None

        records = self._repository.get_entity_records("organization", cnpj)
        activities = tuple(
            sorted(
                (self._activity(record) for record in records),
                key=self._sort_key,
                reverse=True,
            )
        )
        counts = {
            "amendments": self._count(records, "amendment-beneficiaries"),
            "payment_documents": self._count(records, "payment-documents"),
            "payment_orders": self._count(records, "payment-orders"),
            "paid_orders": sum(
                1
                for record in records
                if record.dataset == "payment-orders"
                and str(record.data.get("in_situacao_op", "")).casefold() == "paga"
            ),
            "opportunities": self._count(records, "open-opportunities"),
        }
        totals = {
            "amendments": self._sum(records, "amendment-beneficiaries", "vl_total_emenda"),
            "payment_documents": self._sum(
                records, "payment-documents", "vl_documento_habil"
            ),
            "payment_orders": self._sum(
                records, "payment-orders", "vl_ordem_pagamento"
            ),
            "opportunities": self._sum(
                records, "open-opportunities", "valorTotalEstimado"
            ),
        }
        sources = tuple(
            sorted({f"{record.connector_id}/{record.dataset}" for record in records})
        )
        return OrganizationOverview(
            cnpj=cnpj,
            name=profile.entity.display_name,
            first_seen_at=profile.entity.first_seen_at,
            last_seen_at=profile.entity.last_seen_at,
            sources=sources,
            counts=counts,
            totals=totals,
            activities=activities,
        )

    @staticmethod
    def _count(records: tuple[EntityLinkedRecord, ...], dataset: str) -> int:
        return sum(1 for record in records if record.dataset == dataset)

    @classmethod
    def _sum(
        cls,
        records: tuple[EntityLinkedRecord, ...],
        dataset: str,
        field: str,
    ) -> float:
        return sum(
            cls._number(record.data.get(field)) or 0
            for record in records
            if record.dataset == dataset
        )

    @classmethod
    def _activity(cls, record: EntityLinkedRecord) -> OrganizationActivity:
        data = record.data
        if record.dataset == "amendment-beneficiaries":
            return OrganizationActivity(
                category="amendments",
                dataset=record.dataset,
                external_id=record.external_id,
                title=f"Emenda {data.get('nr_emenda') or record.external_id}",
                description=cls._text(data.get("nm_parlamentar")),
                amount=cls._number(data.get("vl_total_emenda")),
                occurred_at=None,
                occurred_year=cls._year(data.get("aa_emenda")),
                status=cls._text(data.get("in_tipo_emenda_parlamentar")),
                source_url=record.source_url,
            )
        if record.dataset == "payment-documents":
            return OrganizationActivity(
                category="payments",
                dataset=record.dataset,
                external_id=record.external_id,
                title=cls._text(data.get("nr_documento_habil"))
                or f"Documento {record.external_id}",
                description=cls._text(data.get("tx_observacao")),
                amount=cls._number(data.get("vl_documento_habil")),
                occurred_at=cls._datetime(data.get("dt_emissao")),
                occurred_year=None,
                status=cls._text(data.get("in_situacao_dh")),
                source_url=record.source_url,
            )
        if record.dataset == "payment-orders":
            return OrganizationActivity(
                category="payments",
                dataset=record.dataset,
                external_id=record.external_id,
                title=cls._text(data.get("nr_ordem_pagamento"))
                or f"Ordem {record.external_id}",
                description=cls._text(data.get("tx_observacao_op")),
                amount=cls._number(data.get("vl_ordem_pagamento")),
                occurred_at=cls._datetime(data.get("dt_emissao_op")),
                occurred_year=None,
                status=cls._text(data.get("in_situacao_op")),
                source_url=record.source_url,
            )
        organization = data.get("orgaoEntidade")
        unit = data.get("unidadeOrgao")
        organization_name = (
            cls._text(organization.get("razaoSocial"))
            if isinstance(organization, Mapping)
            else None
        )
        location = (
            " / ".join(
                filter(
                    None,
                    (
                        cls._text(unit.get("municipioNome")),
                        cls._text(unit.get("ufSigla")),
                    ),
                )
            )
            if isinstance(unit, Mapping)
            else ""
        )
        return OrganizationActivity(
            category="opportunities",
            dataset=record.dataset,
            external_id=record.external_id,
            title=cls._text(data.get("objetoCompra")) or "Oportunidade de contratação",
            description=" · ".join(filter(None, (organization_name, location))) or None,
            amount=cls._number(data.get("valorTotalEstimado")),
            occurred_at=cls._datetime(
                data.get("dataPublicacaoPncp") or data.get("dataInclusao")
            ),
            occurred_year=None,
            status=cls._text(data.get("situacaoCompraNome")),
            source_url=record.source_url,
        )

    @staticmethod
    def _sort_key(activity: OrganizationActivity) -> datetime:
        if activity.occurred_at is not None:
            return activity.occurred_at
        if activity.occurred_year is not None:
            return datetime(activity.occurred_year, 1, 1, tzinfo=UTC)
        return datetime.min.replace(tzinfo=UTC)

    @staticmethod
    def _text(value: Any) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    @staticmethod
    def _number(value: Any) -> float | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return None
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _datetime(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _year(value: Any) -> int | None:
        try:
            year = int(value)
        except (TypeError, ValueError):
            return None
        return year if 1900 <= year <= 3000 else None
