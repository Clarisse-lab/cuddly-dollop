from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Mapping


def _immutable_copy(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


def content_hash(value: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConnectorSpec:
    id: str
    display_name: str
    datasets: tuple[str, ...]
    version: str = "1"
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class SyncRequest:
    connector_id: str
    dataset: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    connector_config: Mapping[str, Any] = field(default_factory=dict)
    restart: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", _immutable_copy(self.parameters))
        object.__setattr__(self, "connector_config", _immutable_copy(self.connector_config))


@dataclass(frozen=True, slots=True)
class ConnectorRecord:
    external_id: str
    data: Mapping[str, Any]
    source_updated_at: datetime | None = None
    source_url: str | None = None

    def __post_init__(self) -> None:
        if not self.external_id:
            raise ValueError("external_id must not be empty")
        object.__setattr__(self, "data", _immutable_copy(self.data))


@dataclass(frozen=True, slots=True)
class ConnectorPage:
    records: tuple[ConnectorRecord, ...]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class StoredRecord:
    connector_id: str
    dataset: str
    external_id: str
    data: Mapping[str, Any]
    collected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    source_updated_at: datetime | None = None
    source_url: str | None = None
    content_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", _immutable_copy(self.data))
        if not self.content_hash:
            object.__setattr__(self, "content_hash", content_hash(self.data))


@dataclass(frozen=True, slots=True)
class SyncResult:
    connector_id: str
    dataset: str
    records_written: int
    pages_processed: int
    resumed_from: str | None
    completed: bool


@dataclass(frozen=True, slots=True)
class RecordPage:
    records: tuple[StoredRecord, ...]
    total: int
    limit: int
    offset: int
