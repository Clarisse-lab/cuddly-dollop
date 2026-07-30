from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol

from govdata.core.entities import (
    EntityLinkedRecord,
    EntityProfile,
    EntityRecordReferences,
    EntityReference,
    EntitySummary,
)
from govdata.core.models import ConnectorPage, ConnectorSpec, RecordPage, StoredRecord


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> Any:
        import json

        # Passing bytes lets json detect UTF-8/16/32 and byte-order marks.
        return json.loads(self.body)


class HttpClient(Protocol):
    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30,
    ) -> HttpResponse: ...


class PublicDataConnector(ABC):
    """Stable extension contract implemented by every data-source plugin."""

    spec: ConnectorSpec

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self.config = dict(config or {})
        self.validate_config()

    def validate_config(self) -> None:
        """Raise ConnectorConfigurationError for invalid configuration."""

    @abstractmethod
    async def fetch_page(
        self,
        dataset: str,
        parameters: Mapping[str, Any],
        cursor: str | None,
        http: HttpClient,
    ) -> ConnectorPage:
        """Fetch one page. A null next_cursor marks the end of the stream."""


class RecordRepository(Protocol):
    def get_checkpoint(
        self, connector_id: str, dataset: str, scope: str
    ) -> str | None: ...

    def commit_page(
        self,
        connector_id: str,
        dataset: str,
        scope: str,
        records: tuple[StoredRecord, ...],
        next_cursor: str | None,
    ) -> int: ...

    def clear_checkpoint(self, connector_id: str, dataset: str, scope: str) -> None: ...


class RecordQueryRepository(Protocol):
    def list_records(
        self, connector_id: str, dataset: str, limit: int = 100
    ) -> list[dict[str, object]]: ...

    def query_records(
        self,
        connector_id: str,
        dataset: str,
        *,
        limit: int,
        offset: int,
    ) -> RecordPage: ...


class EntityRepository(Protocol):
    def record_entity_links(
        self,
        connector_id: str,
        dataset: str,
        external_id: str,
        refs: tuple[EntityReference, ...],
        observed_at: datetime,
    ) -> None: ...

    def record_entity_links_batch(
        self,
        connector_id: str,
        dataset: str,
        records: tuple[EntityRecordReferences, ...],
        observed_at: datetime,
    ) -> None: ...

    def get_entity_profile(
        self, entity_type: str, entity_id: str
    ) -> EntityProfile | None: ...

    def get_entity_records(
        self, entity_type: str, entity_id: str
    ) -> tuple[EntityLinkedRecord, ...]: ...

    def search_entities(
        self, entity_type: str, query: str, limit: int
    ) -> tuple[EntitySummary, ...]: ...


class DataRepository(RecordRepository, RecordQueryRepository, EntityRepository, Protocol):
    """Complete persistence contract used by API, CLI and synchronization."""
