import os
from pathlib import Path

from govdata.application.entity_resolution import EntityResolutionService
from govdata.application.sync import SyncService
from govdata.connectors.ibge import IBGEConnector
from govdata.core.ports import DataRepository
from govdata.core.registry import ConnectorRegistry
from govdata.infrastructure.http import UrllibHttpClient
from govdata.infrastructure.postgresql import PostgresRecordRepository
from govdata.infrastructure.sqlite import SQLiteRecordRepository


def create_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(IBGEConnector)
    registry.discover()
    return registry


def create_repository(database: str | Path | None = None) -> DataRepository:
    target = str(
        database
        or os.getenv("DATABASE_URL")
        or os.getenv("GOVDATA_DATABASE")
        or "govdata.sqlite3"
    )
    if target.startswith(("postgres://", "postgresql://")):
        return PostgresRecordRepository(target)
    if target.startswith("sqlite:///"):
        target = target.removeprefix("sqlite:///")
    elif "://" in target:
        from govdata.core.errors import DatabaseConfigurationError

        raise DatabaseConfigurationError("unsupported database URL scheme")
    return SQLiteRecordRepository(target)


def create_sync_service(database: str | Path | None = None) -> SyncService:
    return SyncService(
        registry=create_registry(),
        repository=create_repository(database),
        http=UrllibHttpClient(),
    )


def create_entity_resolution_service(
    database: str | Path | None = None,
) -> EntityResolutionService:
    return EntityResolutionService(repository=create_repository(database))
