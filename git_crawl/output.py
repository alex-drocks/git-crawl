from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Iterable, Sequence


def rows_to_dicts(rows: Iterable[object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for row in rows:
        if isinstance(row, Mapping):
            result.append(dict(row))
            continue
        if not is_dataclass(row):
            raise TypeError(f"Expected dataclass row, got {type(row)!r}")
        result.append(asdict(row))
    return result


def write_jsonl(path: str | Path, rows: Iterable[object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows_to_dicts(rows):
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
            handle.write("\n")


def write_csv(
    path: str | Path,
    rows: Iterable[object],
    fieldnames: Sequence[str] | None = None,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    row_dicts = [_escape_spreadsheet_formulas(row) for row in rows_to_dicts(rows)]
    if fieldnames is None:
        fieldnames = list(row_dicts[0].keys()) if row_dicts else []

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(row_dicts)


def _escape_spreadsheet_formulas(row: dict[str, object]) -> dict[str, object]:
    return {key: _escape_spreadsheet_formula_value(value) for key, value in row.items()}


def _escape_spreadsheet_formula_value(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value
