from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import tomllib

VALID_OUTPUT_FORMATS = {"all", "jsonl", "csv"}
VALID_REF_SCOPES = {"default-branch", "all-refs"}


@dataclass(frozen=True)
class CrawlerConfig:
    org: str | None = None
    active_since: str | None = None
    since: str | None = None
    until: str | None = None
    ref_scope: str | None = None
    workers: int | None = None
    cache_dir: str | None = None
    output_dir: str | None = None
    state_db: str | None = None
    max_repos: int | None = None
    include_archived: bool | None = None
    include_forks: bool | None = None
    output_format: str | None = None


def load_config(path: str | Path) -> CrawlerConfig:
    """Load crawler settings from a TOML config file using only stdlib."""
    path = Path(path)
    with path.open("rb") as handle:
        data = tomllib.load(handle)

    filters = _section(data, "filters")
    outputs = _section(data, "outputs")

    return CrawlerConfig(
        org=_optional_str(data.get("org")),
        active_since=_optional_str(data.get("active_since")),
        since=_optional_str(data.get("since")),
        until=_optional_str(data.get("until")),
        ref_scope=_optional_choice(data.get("ref_scope"), VALID_REF_SCOPES, "ref_scope"),
        workers=_optional_positive_int(data.get("workers"), "workers"),
        cache_dir=_optional_str(data.get("cache_dir")),
        output_dir=_optional_str(data.get("output_dir")),
        state_db=_optional_str(data.get("state_db")),
        max_repos=_optional_positive_int(filters.get("max_repos"), "max_repos"),
        include_archived=_optional_bool(filters.get("include_archived")),
        include_forks=_optional_bool(filters.get("include_forks")),
        output_format=_optional_choice(outputs.get("format"), VALID_OUTPUT_FORMATS, "format"),
    )


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"[{name}] must be a TOML table")
    return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Expected string config value, got {value!r}")
    return value


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Expected integer config value, got {value!r}")
    return value


def _optional_positive_int(value: Any, name: str) -> int | None:
    parsed = _optional_int(value)
    if parsed is not None and parsed < 1:
        raise ValueError(f"Expected {name} to be >= 1, got {parsed!r}")
    return parsed


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"Expected boolean config value, got {value!r}")
    return value


def _optional_choice(value: Any, choices: set[str], name: str) -> str | None:
    parsed = _optional_str(value)
    if parsed is not None and parsed not in choices:
        raise ValueError(f"Unsupported {name} config value {parsed!r}; expected one of {sorted(choices)}")
    return parsed
