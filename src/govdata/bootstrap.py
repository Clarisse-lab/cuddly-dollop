from pathlib import Path

from govdata.application.sync import SyncService
from govdata.connectors.ibge import IBGEConnector
from govdata.core.registry import ConnectorRegistry
from govdata.infrastructure.http import UrllibHttpClient
from govdata.infrastructure.sqlite import SQLiteRecordRepository


def create_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(IBGEConnector)
    registry.discover()
    return registry


def create_sync_service(database: str | Path) -> SyncService:
    return SyncService(
        registry=create_registry(),
        repository=SQLiteRecordRepository(database),
        http=UrllibHttpClient(),
    )

