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
