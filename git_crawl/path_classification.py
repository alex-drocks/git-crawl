from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

PATH_CLASS_SOURCE = "source"
PATH_CLASS_LOCKFILE = "lockfile"
PATH_CLASS_GENERATED = "generated"
PATH_CLASS_SPEC = "spec"
PATH_CLASS_DOCS = "docs"
PATH_CLASS_BINARY = "binary"
PATH_CLASS_VENDORED = "vendored"
PATH_CLASS_UNKNOWN = "unknown"

GENERATED_LIKE_CLASSES = {
    PATH_CLASS_LOCKFILE,
    PATH_CLASS_GENERATED,
    PATH_CLASS_SPEC,
    PATH_CLASS_VENDORED,
}
LOCKFILE_NAMES = {
    "bun.lock",
    "bun.lockb",
    "cargo.lock",
    "composer.lock",
    "gemfile.lock",
    "package-lock.json",
    "pipfile.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
}
SOURCE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".lua",
    ".mjs",
    ".py",
    ".rs",
    ".scala",
    ".sh",
    ".sql",
    ".svelte",
    ".swift",
    ".ts",
    ".tsx",
    ".vue",
}
DOC_EXTENSIONS = {".adoc", ".md", ".mdx", ".rst", ".txt"}
SPEC_EXTENSIONS = {".json", ".yaml", ".yml", ".md"}
VENDORED_PARTS = {
    ".venv",
    "node_modules",
    "site-packages",
    "third_party",
    "vendor",
    "vendors",
}
GENERATED_EXACT_PARTS = {
    "__generated__",
    "build",
    "dist",
    "generated",
}
GENERATED_PART_PREFIXES = ("gen_", "generated_")
GENERATED_PART_SUFFIXES = ("_generated",)
GENERATED_PART_SUBSTRINGS = ("autogen", "codegen")
SPEC_NAME_MARKERS = ("openapi", "swagger", "schema", "spec")


@dataclass(frozen=True)
class PathClassification:
    path_class: str
    is_generated_like: bool
    is_lockfile: bool


def classify_path(path: str, *, is_binary: bool = False) -> PathClassification:
    """Classify a changed path for churn interpretation/reporting."""
    normalized = path.replace("\\", "/").strip("/")
    parts = tuple(part for part in PurePosixPath(normalized).parts if part not in {"", "."})
    basename = parts[-1] if parts else normalized
    basename_lower = basename.lower()
    suffix = PurePosixPath(basename_lower).suffix
    parts_lower = tuple(part.lower() for part in parts)

    if basename_lower in LOCKFILE_NAMES or basename_lower.endswith(".lock"):
        return _classification(PATH_CLASS_LOCKFILE)
    if any(part in VENDORED_PARTS for part in parts_lower):
        return _classification(PATH_CLASS_VENDORED)
    if _is_spec_path(parts_lower, basename_lower, suffix):
        return _classification(PATH_CLASS_SPEC)
    if _is_generated_path(parts_lower, basename_lower):
        return _classification(PATH_CLASS_GENERATED)
    if is_binary:
        return _classification(PATH_CLASS_BINARY)
    if parts_lower and parts_lower[0] in {"docs", "doc"} and suffix in DOC_EXTENSIONS:
        return _classification(PATH_CLASS_DOCS)
    if suffix in SOURCE_EXTENSIONS:
        return _classification(PATH_CLASS_SOURCE)
    if suffix in DOC_EXTENSIONS:
        return _classification(PATH_CLASS_DOCS)
    return _classification(PATH_CLASS_UNKNOWN)


def _classification(path_class: str) -> PathClassification:
    return PathClassification(
        path_class=path_class,
        is_generated_like=path_class in GENERATED_LIKE_CLASSES,
        is_lockfile=path_class == PATH_CLASS_LOCKFILE,
    )


def _is_generated_path(parts_lower: tuple[str, ...], basename_lower: str) -> bool:
    if basename_lower == "tokenizer.json":
        return True
    if basename_lower.endswith(".model.json") or basename_lower.endswith(".min.js"):
        return True
    if "tokenizer" in basename_lower and basename_lower.endswith(".json"):
        return True
    return any(_is_generated_part(part) for part in parts_lower)


def _is_generated_part(part: str) -> bool:
    return (
        part in GENERATED_EXACT_PARTS
        or part.startswith(GENERATED_PART_PREFIXES)
        or part.endswith(GENERATED_PART_SUFFIXES)
        or any(marker in part for marker in GENERATED_PART_SUBSTRINGS)
    )


def _is_spec_path(parts_lower: tuple[str, ...], basename_lower: str, suffix: str) -> bool:
    if suffix not in SPEC_EXTENSIONS:
        return False
    if any(marker in basename_lower for marker in SPEC_NAME_MARKERS):
        return True
    return any(part in {"spec", "specs", "schemas", "openapi"} for part in parts_lower)
