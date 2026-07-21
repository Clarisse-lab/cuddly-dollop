from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any, Callable, Mapping

from govdata.core.errors import ConnectorNotFoundError
from govdata.core.models import ConnectorSpec
from govdata.core.ports import PublicDataConnector

ConnectorFactory = Callable[[Mapping[str, Any] | None], PublicDataConnector]


class ConnectorRegistry:
    """Registry populated explicitly or through the ``govdata.connectors`` group."""

    ENTRY_POINT_GROUP = "govdata.connectors"

    def __init__(self) -> None:
        self._factories: dict[str, ConnectorFactory] = {}
        self._specs: dict[str, ConnectorSpec] = {}

    def register(self, factory: ConnectorFactory) -> None:
        spec = getattr(factory, "spec", None)
        if not isinstance(spec, ConnectorSpec):
            raise TypeError("connector factory must expose a ConnectorSpec as 'spec'")
        if spec.id in self._factories:
            raise ValueError(f"connector already registered: {spec.id}")
        self._factories[spec.id] = factory
        self._specs[spec.id] = spec

    def discover(self) -> None:
        for item in entry_points(group=self.ENTRY_POINT_GROUP):
            factory = item.load()
            if item.name not in self._factories:
                self.register(factory)

    def create(
        self, connector_id: str, config: Mapping[str, Any] | None = None
    ) -> PublicDataConnector:
        try:
            factory = self._factories[connector_id]
        except KeyError as error:
            available = ", ".join(sorted(self._factories)) or "none"
            raise ConnectorNotFoundError(
                f"connector '{connector_id}' not found; available: {available}"
            ) from error
        return factory(config)

    def specs(self) -> tuple[ConnectorSpec, ...]:
        return tuple(self._specs[key] for key in sorted(self._specs))
