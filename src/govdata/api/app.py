from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from govdata import __version__
from govdata.api.schemas import (
    ConnectorResponse,
    EntityLinkResponse,
    EntityProfileResponse,
    HealthResponse,
    RecordPageResponse,
    RecordResponse,
)
from govdata.bootstrap import create_registry, create_repository
from govdata.core.ports import DataRepository
from govdata.core.registry import ConnectorRegistry

LOCAL_DEVELOPMENT_ORIGINS = (
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


@dataclass(frozen=True, slots=True)
class ApiSettings:
    database: str | Path | None
    cors_origins: tuple[str, ...]

    @classmethod
    def from_environment(cls) -> "ApiSettings":
        raw_origins = os.getenv("GOVDATA_CORS_ORIGINS", "")
        configured_origins = tuple(
            origin.strip() for origin in raw_origins.split(",") if origin.strip()
        )
        return cls(
            database=os.getenv("DATABASE_URL") or os.getenv("GOVDATA_DATABASE"),
            cors_origins=tuple(
                dict.fromkeys((*LOCAL_DEVELOPMENT_ORIGINS, *configured_origins))
            ),
        )


def create_app(
    *,
    settings: ApiSettings | None = None,
    registry: ConnectorRegistry | None = None,
    repository: DataRepository | None = None,
) -> FastAPI:
    settings = settings or ApiSettings.from_environment()
    registry = registry or create_registry()
    repository = repository or create_repository(settings.database)

    application = FastAPI(
        title="Dados Gov API",
        version=__version__,
        description="API de leitura para dados públicos coletados pela plataforma.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @application.get(
        "/api/v1/connectors",
        response_model=list[ConnectorResponse],
        tags=["catalog"],
    )
    def connectors() -> list[ConnectorResponse]:
        return [
            ConnectorResponse(
                id=spec.id,
                name=spec.display_name,
                version=spec.version,
                datasets=list(spec.datasets),
                source_url=spec.source_url,
            )
            for spec in registry.specs()
        ]

    @application.get(
        "/api/v1/records/{connector_id}/{dataset}",
        response_model=RecordPageResponse,
        tags=["records"],
    )
    def records(
        connector_id: str,
        dataset: str,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> RecordPageResponse:
        specs = {spec.id: spec for spec in registry.specs()}
        spec = specs.get(connector_id)
        if spec is None:
            raise HTTPException(status_code=404, detail="connector not found")
        if dataset not in spec.datasets:
            raise HTTPException(status_code=404, detail="dataset not found")

        page = repository.query_records(
            connector_id,
            dataset,
            limit=limit,
            offset=offset,
        )
        return RecordPageResponse(
            items=[
                RecordResponse(
                    external_id=record.external_id,
                    data=dict(record.data),
                    collected_at=record.collected_at,
                    source_updated_at=record.source_updated_at,
                    source_url=record.source_url,
                    content_hash=record.content_hash,
                )
                for record in page.records
            ],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    @application.get(
        "/api/v1/entities/{entity_type}/{entity_id}",
        response_model=EntityProfileResponse,
        tags=["entities"],
    )
    def entity(entity_type: str, entity_id: str) -> EntityProfileResponse:
        profile = repository.get_entity_profile(entity_type, entity_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="entity not found")
        return EntityProfileResponse(
            entity_type=profile.entity.entity_type,
            entity_id=profile.entity.entity_id,
            display_name=profile.entity.display_name,
            first_seen_at=profile.entity.first_seen_at,
            last_seen_at=profile.entity.last_seen_at,
            links=[
                EntityLinkResponse(
                    connector_id=link.connector_id,
                    dataset=link.dataset,
                    external_id=link.external_id,
                    role=link.role,
                    linked_at=link.linked_at,
                )
                for link in profile.links
            ],
        )

    return application


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run(
        "govdata.api.app:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
