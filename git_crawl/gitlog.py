from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

GIT_LOG_RECORD_SEPARATOR = "\x1e"
GIT_LOG_FIELD_SEPARATOR = "\x1f"
GIT_LOG_FORMAT = "%x1e%H%x1f%an%x1f%ae%x1f%aI%x1f%P"


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
    is_binary = additions_raw == "-" or deletions_raw == "-"
    additions = 0 if is_binary else int(additions_raw)
    deletions = 0 if is_binary else int(deletions_raw)
    return FileChange(
        additions=additions,
        deletions=deletions,
        path=path,
        is_binary=is_binary,
    )


def parse_git_log(output: str, repo: str) -> list[CommitRecord]:
    """Parse `git log --numstat` output produced with ``GIT_LOG_FORMAT``.

    Binary file changes are counted as changed files but contribute zero added
    or deleted text lines because git emits ``-\t-`` for their numstat fields.
    """
    commits: list[CommitRecord] = []
    for raw_record in output.split(GIT_LOG_RECORD_SEPARATOR):
        if not raw_record.strip():
            continue

        lines = raw_record.splitlines()
        if not lines:
            continue

        fields = lines[0].split(GIT_LOG_FIELD_SEPARATOR)
        if len(fields) != 5:
            raise ValueError(f"Unexpected git log header for {repo}: {lines[0]!r}")

        sha, author_name, author_email, authored_at_raw, parents_raw = fields
        changes = [
            change
            for line in lines[1:]
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
