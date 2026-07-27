from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping


@dataclass(frozen=True, slots=True)
class OrganizationActivity:
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


@dataclass(frozen=True, slots=True)
class OrganizationOverview:
    cnpj: str
    name: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    sources: tuple[str, ...]
    counts: Mapping[str, int]
    totals: Mapping[str, float]
    activities: tuple[OrganizationActivity, ...]
