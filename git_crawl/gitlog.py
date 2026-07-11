from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

GIT_LOG_RECORD_SEPARATOR = "\x1e"
GIT_LOG_FIELD_SEPARATOR = "\x1f"
GIT_LOG_FORMAT = "%x1e%H%x1f%an%x1f%ae%x1f%aI%x1f%P"
GIT_LOG_NUL_RECORD_RE = re.compile(r"(?:^|\0)\x1e(?=[0-9a-f]+\x1f)")


@dataclass(frozen=True)
class FileChange:
    additions: int
    deletions: int
    path: str
    is_binary: bool = False


@dataclass(frozen=True)
class CommitRecord:
    repo: str
    sha: str
    author_name: str
    author_email: str
    author_login: str | None
    authored_at: datetime
    parents: list[str]
    changes: list[FileChange]


def parse_author_login(email: str) -> str | None:
    """Extract a GitHub login from public GitHub noreply email formats."""
    local, sep, domain = email.lower().partition("@")
    if sep != "@" or domain != "users.noreply.github.com" or not local:
        return None
    if "+" in local:
        return local.split("+", 1)[1] or None
    return local


def parse_git_datetime(value: str) -> datetime:
    """Parse git's ISO-strict author timestamp."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_numstat_line(line: str) -> FileChange | None:
    parts = line.split("\t", 2)
    if len(parts) != 3:
        return None

    additions_raw, deletions_raw, path = parts
    return _file_change(additions_raw, deletions_raw, path)


def _file_change(additions_raw: str, deletions_raw: str, path: str) -> FileChange:
    is_binary = additions_raw == "-" or deletions_raw == "-"
    additions = 0 if is_binary else int(additions_raw)
    deletions = 0 if is_binary else int(deletions_raw)
    return FileChange(
        additions=additions,
        deletions=deletions,
        path=path,
        is_binary=is_binary,
    )


def _parse_nul_numstat(body: str) -> list[FileChange]:
    """Parse ``git log --numstat -z`` paths without Git's display quoting."""
    tokens = body.removeprefix("\n").split("\0")
    changes: list[FileChange] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token:
            index += 1
            continue

        parts = token.split("\t", 2)
        if len(parts) != 3:
            index += 1
            continue

        additions_raw, deletions_raw, path = parts
        if path:
            changes.append(_file_change(additions_raw, deletions_raw, path))
            index += 1
            continue

        # With -z, rename/copy records put the old and new paths in the next
        # two NUL-delimited fields. The destination is the changed path exposed
        # by GitHub and the useful path for downstream classification.
        if index + 2 >= len(tokens):
            break
        destination_path = tokens[index + 2]
        if destination_path:
            changes.append(_file_change(additions_raw, deletions_raw, destination_path))
        index += 3

    return changes


def _git_log_records(output: str) -> list[str]:
    if "\0" not in output:
        return output.split(GIT_LOG_RECORD_SEPARATOR)
    # In -z output Git inserts a NUL before every header after the first. Match
    # that structural boundary so a literal record-separator byte in a path is
    # preserved rather than mistaken for the next commit.
    return GIT_LOG_NUL_RECORD_RE.split(output)


def parse_git_log(output: str, repo: str) -> list[CommitRecord]:
    """Parse `git log --numstat -z` output produced with ``GIT_LOG_FORMAT``.

    Binary file changes are counted as changed files but contribute zero added
    or deleted text lines because git emits ``-\t-`` for their numstat fields.
    Legacy line-delimited output remains accepted for callers of this function.
    """
    commits: list[CommitRecord] = []
    for raw_record in _git_log_records(output):
        if not raw_record.strip():
            continue

        header, newline, body = raw_record.partition("\n")
        if not header:
            continue

        fields = header.split(GIT_LOG_FIELD_SEPARATOR)
        if len(fields) != 5:
            raise ValueError(f"Unexpected git log header for {repo}: {header!r}")

        sha, author_name, author_email, authored_at_raw, parents_raw = fields
        if "\0" in body:
            changes = _parse_nul_numstat(body)
        else:
            lines = body.splitlines() if newline else []
            changes = [
                change
                for line in lines
                if line.strip()
                for change in [_parse_numstat_line(line)]
                if change is not None
            ]

        commits.append(
            CommitRecord(
                repo=repo,
                sha=sha,
                author_name=author_name,
                author_email=author_email,
                author_login=parse_author_login(author_email),
                authored_at=parse_git_datetime(authored_at_raw),
                parents=parents_raw.split() if parents_raw else [],
                changes=changes,
            )
        )

    return commits
