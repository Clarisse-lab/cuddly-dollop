from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from govdata.bootstrap import (
    create_entity_resolution_service,
    create_registry,
    create_repository,
    create_sync_service,
)
from govdata.core.errors import GovDataError
from govdata.core.models import SyncRequest


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError(f"invalid JSON: {error.msg}") from error
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("value must be a JSON object")
    return value


def _key_value(raw: str) -> tuple[str, Any]:
    key, separator, raw_value = raw.partition("=")
    if not separator or not key.strip():
        raise argparse.ArgumentTypeError("expected KEY=VALUE")
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value
    return key.strip(), value


def _merge_values(base: dict[str, Any], pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    return {**base, **dict(pairs)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="govdata")
    parser.add_argument(
        "--database",
        default=os.getenv("DATABASE_URL") or os.getenv("GOVDATA_DATABASE"),
        help="database path or URL; defaults to DATABASE_URL or local SQLite",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("connectors", help="list installed connectors")
    sync = subparsers.add_parser("sync", help="synchronize a dataset")
    sync.add_argument("connector")
    sync.add_argument("dataset")
    sync.add_argument("--params", type=_json_object, default={}, help="parameters as JSON")
    sync.add_argument(
        "--param",
        action="append",
        type=_key_value,
        default=[],
        metavar="KEY=VALUE",
        help="repeatable and safe in PowerShell",
    )
    sync.add_argument("--config", type=_json_object, default={}, help="configuration as JSON")
    sync.add_argument(
        "--set-config",
        action="append",
        type=_key_value,
        default=[],
        metavar="KEY=VALUE",
        help="repeatable connector configuration",
    )
    sync.add_argument("--restart", action="store_true")

    sync_many = subparsers.add_parser(
        "sync-many", help="synchronize multiple datasets from one connector"
    )
    sync_many.add_argument("connector")
    sync_many.add_argument("datasets", nargs="+")
    sync_many.add_argument(
        "--config", type=_json_object, default={}, help="configuration as JSON"
    )
    sync_many.add_argument(
        "--set-config",
        action="append",
        type=_key_value,
        default=[],
        metavar="KEY=VALUE",
        help="repeatable connector configuration",
    )
    sync_many.add_argument("--restart", action="store_true")

    records = subparsers.add_parser("records", help="read collected records")
    records.add_argument("connector")
    records.add_argument("dataset")
    records.add_argument("--limit", type=int, default=100)

    subparsers.add_parser(
        "link", help="resolve cross-source entities (organizations, locations)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "connectors":
            output = [
                {
                    "id": spec.id,
                    "name": spec.display_name,
                    "version": spec.version,
                    "datasets": spec.datasets,
                    "source_url": spec.source_url,
                }
                for spec in create_registry().specs()
            ]
        elif args.command == "sync":
            result = asyncio.run(
                create_sync_service(args.database).run(
                    SyncRequest(
                        connector_id=args.connector,
                        dataset=args.dataset,
                        parameters=_merge_values(args.params, args.param),
                        connector_config=_merge_values(args.config, args.set_config),
                        restart=args.restart,
                    )
                )
            )
            output = {
                "connector": result.connector_id,
                "dataset": result.dataset,
                "records_written": result.records_written,
                "pages_processed": result.pages_processed,
                "resumed_from": result.resumed_from,
                "completed": result.completed,
            }
        elif args.command == "sync-many":
            service = create_sync_service(args.database)
            results = [
                asyncio.run(
                    service.run(
                        SyncRequest(
                            connector_id=args.connector,
                            dataset=dataset,
                            connector_config=_merge_values(
                                args.config, args.set_config
                            ),
                            restart=args.restart,
                        )
                    )
                )
                for dataset in args.datasets
            ]
            output = [
                {
                    "connector": result.connector_id,
                    "dataset": result.dataset,
                    "records_written": result.records_written,
                    "pages_processed": result.pages_processed,
                    "resumed_from": result.resumed_from,
                    "completed": result.completed,
                }
                for result in results
            ]
        elif args.command == "link":
            output = create_entity_resolution_service(args.database).run()
        else:
            output = create_repository(args.database).list_records(
                args.connector, args.dataset, args.limit
            )
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (GovDataError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
