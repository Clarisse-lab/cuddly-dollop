from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from time import monotonic
from typing import Any, Mapping

from govdata.bootstrap import create_sync_service
from govdata.core.errors import GovDataError
from govdata.core.models import SyncRequest


@dataclass(frozen=True, slots=True)
class SanctionSyncTask:
    dataset: str
    parameters: Mapping[str, Any]


def build_sync_plan(
    today: date,
    *,
    full: bool = False,
    lookback_days: int = 30,
) -> tuple[SanctionSyncTask, ...]:
    if lookback_days < 1:
        raise ValueError("lookback_days must be greater than zero")
    if full or today.weekday() == 6:
        return tuple(
            SanctionSyncTask(dataset, {}) for dataset in ("ceis", "cnep", "cepim")
        )
    start = today - timedelta(days=lookback_days)
    period = {
        "dataInicialSancao": start.strftime("%d/%m/%Y"),
        "dataFinalSancao": today.strftime("%d/%m/%Y"),
    }
    return (
        SanctionSyncTask("ceis", period),
        SanctionSyncTask("cnep", period),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="govdata-transparencia-sanctions")
    parser.add_argument(
        "--full",
        action="store_true",
        help="force a complete CEIS, CNEP and CEPIM reconciliation",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=30,
        help="rolling CEIS/CNEP window used on non-Sundays",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    today = datetime.now(UTC).date()
    try:
        plan = build_sync_plan(
            today,
            full=args.full,
            lookback_days=args.lookback_days,
        )
        mode = "full" if args.full or today.weekday() == 6 else "incremental"
        print(
            json.dumps(
                {
                    "event": "sanctions_sync_started",
                    "mode": mode,
                    "datasets": [task.dataset for task in plan],
                    "date": today.isoformat(),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        service = create_sync_service()
        results: list[dict[str, Any]] = []
        for task in plan:
            started_at = monotonic()
            print(
                json.dumps(
                    {
                        "event": "dataset_sync_started",
                        "dataset": task.dataset,
                        "parameters": dict(task.parameters),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            result = asyncio.run(
                service.run(
                    SyncRequest(
                        connector_id="transparencia",
                        dataset=task.dataset,
                        parameters=task.parameters,
                    )
                )
            )
            summary = {
                "dataset": result.dataset,
                "records_written": result.records_written,
                "pages_processed": result.pages_processed,
                "resumed_from": result.resumed_from,
                "completed": result.completed,
                "elapsed_seconds": round(monotonic() - started_at, 2),
            }
            results.append(summary)
            print(
                json.dumps(
                    {"event": "dataset_sync_completed", **summary},
                    ensure_ascii=False,
                ),
                flush=True,
            )
        print(
            json.dumps(
                {
                    "event": "sanctions_sync_completed",
                    "mode": mode,
                    "results": results,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 0
    except (GovDataError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
