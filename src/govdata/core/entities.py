from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class EntityReference:
    entity_type: str
    entity_id: str
    display_name: str | None = None
    role: str | None = None


@dataclass(frozen=True, slots=True)
class EntityRecordReferences:
    external_id: str
    references: tuple[EntityReference, ...]


@dataclass(frozen=True, slots=True)
class EntityLink:
    connector_id: str
    dataset: str
    external_id: str
    role: str | None
    linked_at: datetime


@dataclass(frozen=True, slots=True)
class Entity:
    entity_type: str
    entity_id: str
    display_name: str | None
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True, slots=True)
class EntityProfile:
    entity: Entity
    links: tuple[EntityLink, ...]
