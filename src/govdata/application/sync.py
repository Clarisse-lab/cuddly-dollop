from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from govdata.core.errors import DatasetNotSupportedError, InvalidResponseError
from govdata.core.models import StoredRecord, SyncRequest, SyncResult
from govdata.core.ports import HttpClient, RecordRepository
from govdata.core.registry import ConnectorRegistry


class SyncService:
    def __init__(
        self,
        registry: ConnectorRegistry,
        repository: RecordRepository,
        http: HttpClient,
    ) -> None:
        self._registry = registry
        self._repository = repository
        self._http = http

    async def run(self, request: SyncRequest) -> SyncResult:
        connector = self._registry.create(request.connector_id, request.connector_config)
        if request.dataset not in connector.spec.datasets:
            raise DatasetNotSupportedError(
                f"dataset '{request.dataset}' is not supported by '{connector.spec.id}'"
            )

        scope = self._checkpoint_scope(request)
        if request.restart:
            self._repository.clear_checkpoint(connector.spec.id, request.dataset, scope)
        cursor = self._repository.get_checkpoint(connector.spec.id, request.dataset, scope)
        resumed_from = cursor
        pages = written = 0
        seen_cursors: set[str | None] = set()

        while True:
            if cursor in seen_cursors:
                raise InvalidResponseError(f"connector returned a repeated cursor: {cursor!r}")
            seen_cursors.add(cursor)
            page = await connector.fetch_page(
                request.dataset, request.parameters, cursor, self._http
            )
            collected_at = datetime.now(UTC)
            records = tuple(
                StoredRecord(
                    connector_id=connector.spec.id,
                    dataset=request.dataset,
                    external_id=item.external_id,
                    data=item.data,
                    collected_at=collected_at,
                    source_updated_at=item.source_updated_at,
                    source_url=item.source_url,
                )
                for item in page.records
            )
            written += self._repository.commit_page(
                connector.spec.id, request.dataset, scope, records, page.next_cursor
            )
            pages += 1
            cursor = page.next_cursor
            if cursor is None:
                break

        return SyncResult(
            connector_id=connector.spec.id,
            dataset=request.dataset,
            records_written=written,
            pages_processed=pages,
            resumed_from=resumed_from,
            completed=True,
        )

    @staticmethod
    def _checkpoint_scope(request: SyncRequest) -> str:
        try:
            serialized = json.dumps(
                dict(request.parameters), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        except (TypeError, ValueError) as error:
            raise ValueError("sync parameters must be JSON-serializable") from error
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
