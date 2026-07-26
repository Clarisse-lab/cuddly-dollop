from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from govdata.application.entity_resolution import (
    EntityResolutionService,
    _cnpj,
    _pncp_open_opportunities,
    _transferegov_amendment_beneficiaries,
    _transferegov_payment_documents,
)
from govdata.core.entities import EntityReference
from govdata.core.models import StoredRecord
from govdata.infrastructure.sqlite import SQLiteRecordRepository


class CnpjNormalizationTests(unittest.TestCase):
    def test_accepts_formatted_cnpj(self) -> None:
        self.assertEqual(_cnpj("12.345.678/0001-00"), "12345678000100")

    def test_rejects_cpf_length(self) -> None:
        self.assertIsNone(_cnpj("123.456.789-00"))

    def test_rejects_missing_value(self) -> None:
        self.assertIsNone(_cnpj(None))


class PNCPExtractorTests(unittest.TestCase):
    def test_extracts_organization_from_confirmed_field(self) -> None:
        refs = _pncp_open_opportunities(
            {
                "orgaoEntidade": {"cnpj": "12345678000100", "razaoSocial": "Prefeitura"},
                "objetoCompra": "Aquisição de equipamentos",
            }
        )

        self.assertIn(
            EntityReference("organization", "12345678000100", "Prefeitura", role="buyer"),
            refs,
        )

    def test_ignores_missing_unit_information(self) -> None:
        refs = _pncp_open_opportunities({"orgaoEntidade": {"cnpj": "12345678000100"}})

        self.assertEqual(
            refs, (EntityReference("organization", "12345678000100", None, role="buyer"),)
        )

    def test_extracts_best_effort_location_when_present(self) -> None:
        refs = _pncp_open_opportunities(
            {
                "orgaoEntidade": {"cnpj": "12345678000100"},
                "unidadeOrgao": {"ufSigla": "sp"},
            }
        )

        self.assertIn(EntityReference("location", "SP", role="buyer-location"), refs)


class TransferegovExtractorTests(unittest.TestCase):
    def test_extracts_organization_and_location(self) -> None:
        refs = _transferegov_amendment_beneficiaries(
            {
                "nr_cnpj_beneficiario_emenda": "11903220000141",
                "nm_beneficiario_emenda": "FUNDO MUNICIPAL DE SAUDE",
                "sg_uf_beneficiario_emenda": "PI",
            }
        )

        self.assertIn(
            EntityReference(
                "organization",
                "11903220000141",
                "FUNDO MUNICIPAL DE SAUDE",
                role="beneficiary",
            ),
            refs,
        )
        self.assertIn(EntityReference("location", "PI", role="beneficiary-location"), refs)

    def test_skips_individual_cpf_beneficiaries(self) -> None:
        refs = _transferegov_amendment_beneficiaries(
            {
                "nr_cnpj_beneficiario_emenda": "12345678900",
                "nm_beneficiario_emenda": "Pessoa Fisica",
                "sg_uf_beneficiario_emenda": "SP",
            }
        )

        self.assertNotIn("organization", [ref.entity_type for ref in refs])
        self.assertIn(EntityReference("location", "SP", role="beneficiary-location"), refs)

    def test_extracts_payment_document_payee(self) -> None:
        refs = _transferegov_payment_documents(
            {
                "cd_credor_devedor": "11.341.134/0001-92",
                "nm_credor_devedor": "FUNDO MUNICIPAL DE SAUDE",
                "id_parceria": 18573,
            }
        )

        self.assertEqual(
            refs,
            (
                EntityReference(
                    "organization",
                    "11341134000192",
                    "FUNDO MUNICIPAL DE SAUDE",
                    role="payee",
                ),
            ),
        )

    def test_skips_payment_document_without_cnpj(self) -> None:
        self.assertEqual(
            _transferegov_payment_documents(
                {
                    "cd_credor_devedor": "12345678900",
                    "nm_credor_devedor": "Pessoa Fisica",
                }
            ),
            (),
        )


class EntityResolutionServiceTests(unittest.TestCase):
    def test_links_matching_cnpj_across_two_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "resolution.sqlite3"
            repository = SQLiteRecordRepository(path)
            collected_at = datetime(2026, 7, 25, tzinfo=UTC)

            repository.commit_page(
                "pncp",
                "open-opportunities",
                "scope",
                (
                    StoredRecord(
                        connector_id="pncp",
                        dataset="open-opportunities",
                        external_id="12345678000100-1-000001/2026",
                        data={
                            "orgaoEntidade": {
                                "cnpj": "12345678000100",
                                "razaoSocial": "Prefeitura Exemplo",
                            }
                        },
                        collected_at=collected_at,
                    ),
                ),
                None,
            )
            repository.commit_page(
                "transferegov",
                "amendment-beneficiaries",
                "scope",
                (
                    StoredRecord(
                        connector_id="transferegov",
                        dataset="amendment-beneficiaries",
                        external_id="11983",
                        data={
                            "nr_cnpj_beneficiario_emenda": "12345678000100",
                            "nm_beneficiario_emenda": "Prefeitura Exemplo",
                            "sg_uf_beneficiario_emenda": "SP",
                        },
                        collected_at=collected_at,
                    ),
                ),
                None,
            )

            summary = EntityResolutionService(repository).run()

            self.assertEqual(summary["records_processed"], 2)
            self.assertGreater(summary["links_written"], 0)

            profile = repository.get_entity_profile("organization", "12345678000100")
            self.assertIsNotNone(profile)
            assert profile is not None
            self.assertEqual(profile.entity.display_name, "Prefeitura Exemplo")
            connectors_linked = {link.connector_id for link in profile.links}
            self.assertEqual(connectors_linked, {"pncp", "transferegov"})

    def test_running_twice_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "idempotent.sqlite3"
            repository = SQLiteRecordRepository(path)
            repository.commit_page(
                "pncp",
                "open-opportunities",
                "scope",
                (
                    StoredRecord(
                        connector_id="pncp",
                        dataset="open-opportunities",
                        external_id="1",
                        data={"orgaoEntidade": {"cnpj": "12345678000100"}},
                        collected_at=datetime(2026, 7, 25, tzinfo=UTC),
                    ),
                ),
                None,
            )

            service = EntityResolutionService(repository)
            service.run()
            service.run()

            profile = repository.get_entity_profile("organization", "12345678000100")
            assert profile is not None
            self.assertEqual(len(profile.links), 1)

    def test_returns_none_for_unknown_entity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "empty.sqlite3"
            repository = SQLiteRecordRepository(path)

            self.assertIsNone(repository.get_entity_profile("organization", "00000000000000"))


if __name__ == "__main__":
    unittest.main()
