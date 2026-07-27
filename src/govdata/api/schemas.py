from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    status: str
    version: str


class ConnectorResponse(BaseModel):
    id: str
    name: str
    version: str
    datasets: list[str]
    source_url: str | None


class RecordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str
    data: dict[str, Any]
    collected_at: datetime
    source_updated_at: datetime | None
    source_url: str | None
    content_hash: str


class RecordPageResponse(BaseModel):
    items: list[RecordResponse]
    total: int
    limit: int
    offset: int


class EntityLinkResponse(BaseModel):
    connector_id: str
    dataset: str
    external_id: str
    role: str | None
    linked_at: datetime


class EntityProfileResponse(BaseModel):
    entity_type: str
    entity_id: str
    display_name: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    links: list[EntityLinkResponse]


class OrganizationActivityResponse(BaseModel):
    category: str
    dataset: str
    external_id: str
    title: str
    description: str | None
    amount: float | None
    occurred_at: datetime | None
    occurred_year: int | None
    status: str | None
    source_url: str | None


class OrganizationOverviewResponse(BaseModel):
    cnpj: str
    name: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    sources: list[str]
    counts: dict[str, int]
    totals: dict[str, float]
    activities: list[OrganizationActivityResponse]
