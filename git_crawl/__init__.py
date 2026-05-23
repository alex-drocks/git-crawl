"""GitHub repository and organization Git history crawler."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _resolve_version() -> str:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    if pyproject.exists():
        try:
            return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
        except (OSError, KeyError, tomllib.TOMLDecodeError):
            return "0+unknown"

    try:
        return version("git-crawl")
    except PackageNotFoundError:
        return "0+unknown"


__version__ = _resolve_version()
