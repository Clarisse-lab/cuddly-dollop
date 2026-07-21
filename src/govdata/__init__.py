"""Extensible public-data integration platform."""

from govdata.application.sync import SyncService
from govdata.core.models import ConnectorSpec, SyncRequest, SyncResult

__all__ = ["ConnectorSpec", "SyncRequest", "SyncResult", "SyncService"]
__version__ = "0.1.0"

