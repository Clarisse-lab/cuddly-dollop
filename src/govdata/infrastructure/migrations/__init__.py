from __future__ import annotations

from importlib.resources import files


def load_migrations(package: str) -> tuple[tuple[str, str], ...]:
    root = files(package)
    resources = sorted(
        (item for item in root.iterdir() if item.name.endswith(".sql")),
        key=lambda item: item.name,
    )
    return tuple((item.name, item.read_text(encoding="utf-8")) for item in resources)
