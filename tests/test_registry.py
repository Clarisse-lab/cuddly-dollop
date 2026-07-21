import unittest

from govdata.connectors.ibge import IBGEConnector
from govdata.core.models import ConnectorSpec
from govdata.core.ports import PublicDataConnector
from govdata.core.errors import ConnectorNotFoundError
from govdata.core.registry import ConnectorRegistry


class ConfiguredConnector(PublicDataConnector):
    spec = ConnectorSpec(id="configured", display_name="Configured", datasets=("data",))

    def validate_config(self) -> None:
        if "token" not in self.config:
            raise ValueError("token required")

    async def fetch_page(self, dataset, parameters, cursor, http):  # type: ignore[no-untyped-def]
        raise NotImplementedError


class RegistryTests(unittest.TestCase):
    def test_registers_and_creates_connector_without_core_changes(self) -> None:
        registry = ConnectorRegistry()
        registry.register(IBGEConnector)

        self.assertIsInstance(registry.create("ibge"), IBGEConnector)

    def test_unknown_connector_has_domain_error(self) -> None:
        with self.assertRaises(ConnectorNotFoundError):
            ConnectorRegistry().create("missing")

    def test_rejects_duplicate_ids(self) -> None:
        registry = ConnectorRegistry()
        registry.register(IBGEConnector)
        with self.assertRaises(ValueError):
            registry.register(IBGEConnector)

    def test_registration_does_not_require_runtime_secrets(self) -> None:
        registry = ConnectorRegistry()
        registry.register(ConfiguredConnector)

        self.assertEqual(registry.specs()[0].id, "configured")
        self.assertIsInstance(registry.create("configured", {"token": "secret"}), ConfiguredConnector)


if __name__ == "__main__":
    unittest.main()
