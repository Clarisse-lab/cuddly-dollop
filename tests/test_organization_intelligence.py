from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from govdata.application.entity_resolution import EntityResolutionService
from govdata.application.organization_intelligence import (
    OrganizationIntelligenceService,
)
from govdata.core.models import StoredRecord
from govdata.infrastructure.sqlite import SQLiteRecordRepository


class OrganizationIntelligenceServiceTests(unittest.TestCase):
    def test_consolidates_amendments_payments_and_opportunities(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repository = SQLiteRecordRepository(Path(temp) / "overview.sqlite3")
            collected_at = datetime(2026, 7, 25, tzinfo=UTC)
            cnpj = "11341134000192"
            records = (
                (
                    "pncp",
                    "open-opportunities",
                    "opportunity-1",
                    {
                        "orgaoEntidade": {
                            "cnpj": cnpj,
                            "razaoSocial": "FUNDO MUNICIPAL DE SAUDE",
                        },
                        "objetoCompra": "Aquisição de equipamentos",
                        "valorTotalEstimado": 150000,
                        "dataPublicacaoPncp": "2026-07-20T12:00:00Z",
                    },
                ),
                (
                    "pncp",
                    "contracts",
                    "contract-1",
                    {
                        "numeroControlePNCP": "99999999000199-2-000001/2026",
                        "numeroContratoEmpenho": "15/2026",
                        "anoContrato": 2026,
                        "sequencialContrato": 1,
                        "orgaoEntidade": {
                            "cnpj": "99999999000199",
                            "razaoSocial": "PREFEITURA CONTRATANTE",
                        },
                        "unidadeOrgao": {
                            "municipioNome": "Teresina",
                            "ufSigla": "PI",
                        },
                        "niFornecedor": cnpj,
                        "nomeRazaoSocialFornecedor": "FUNDO MUNICIPAL DE SAUDE",
                        "objetoContrato": "Manutenção de equipamentos",
                        "valorGlobal": 175000,
                        "dataAssinatura": "2026-07-23",
                        "tipoContrato": {"nome": "Contrato"},
                    },
                ),
                (
                    "transferegov",
                    "amendment-beneficiaries",
                    "beneficiary-1",
                    {
                        "nr_cnpj_beneficiario_emenda": cnpj,
                        "nm_beneficiario_emenda": "FUNDO MUNICIPAL DE SAUDE",
                        "nr_emenda": "2026.0001",
                        "aa_emenda": 2026,
                        "vl_total_emenda": 200000,
                    },
                ),
                (
                    "transferegov",
                    "payment-documents",
                    "278",
                    {
                        "id_documento_habil": 278,
                        "cd_credor_devedor": cnpj,
                        "nm_credor_devedor": "FUNDO MUNICIPAL DE SAUDE",
                        "nr_documento_habil": "2025TF845786",
                        "vl_documento_habil": 100000,
                        "dt_emissao": "2025-08-28T00:00:00",
                    },
                ),
                (
                    "transferegov",
                    "payment-orders",
                    "276",
                    {
                        "id_op": 276,
                        "id_documento_habil": 278,
                        "nr_ordem_pagamento": "2025OP040959",
                        "in_situacao_op": "Paga",
                        "vl_ordem_pagamento": 100000,
                        "dt_emissao_op": "2025-08-28T00:00:00",
                    },
                ),
                (
                    "transparencia",
                    "cnep",
                    "sanction-1",
                    {
                        "id": 901,
                        "sancionado": {
                            "codigoFormatado": cnpj,
                            "nome": "FUNDO MUNICIPAL DE SAUDE",
                        },
                        "tipoSancao": {
                            "descricaoResumida": "Multa",
                            "descricaoPortal": "Multa administrativa",
                        },
                        "orgaoSancionador": {"nome": "Órgão de Controle"},
                        "numeroProcesso": "0001/2026",
                        "valorMulta": "25.000,00",
                        "dataPublicacaoSancao": "20/07/2026",
                    },
                ),
            )
            for connector_id, dataset, external_id, data in records:
                repository.commit_page(
                    connector_id,
                    dataset,
                    "scope",
                    (
                        StoredRecord(
                            connector_id=connector_id,
                            dataset=dataset,
                            external_id=external_id,
                            data=data,
                            collected_at=collected_at,
                        ),
                    ),
                    None,
                )

            EntityResolutionService(repository).run()
            overview = OrganizationIntelligenceService(repository).get(cnpj)

            assert overview is not None
            self.assertEqual(overview.name, "FUNDO MUNICIPAL DE SAUDE")
            self.assertEqual(overview.counts["amendments"], 1)
            self.assertEqual(overview.counts["payment_orders"], 1)
            self.assertEqual(overview.counts["paid_orders"], 1)
            self.assertEqual(overview.counts["opportunities"], 1)
            self.assertEqual(overview.counts["contracts"], 1)
            self.assertEqual(overview.counts["cnep"], 1)
            self.assertEqual(overview.counts["integrity_occurrences"], 1)
            self.assertEqual(overview.totals["amendments"], 200000)
            self.assertEqual(overview.totals["payment_orders"], 100000)
            self.assertEqual(overview.totals["opportunities"], 150000)
            self.assertEqual(overview.totals["contracts"], 175000)
            self.assertEqual(
                {activity.category for activity in overview.activities},
                {"amendments", "payments", "opportunities", "contracts", "integrity"},
            )
            amendment = next(
                activity
                for activity in overview.activities
                if activity.category == "amendments"
            )
            self.assertIsNone(amendment.occurred_at)
            self.assertEqual(amendment.occurred_year, 2026)
            integrity = next(
                activity
                for activity in overview.activities
                if activity.category == "integrity"
            )
            self.assertEqual(integrity.amount, 25000)
            self.assertEqual(integrity.occurred_at, datetime(2026, 7, 20, tzinfo=UTC))

    def test_returns_none_for_unknown_organization(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repository = SQLiteRecordRepository(Path(temp) / "empty.sqlite3")

            self.assertIsNone(
                OrganizationIntelligenceService(repository).get("00000000000000")
            )


if __name__ == "__main__":
    unittest.main()
