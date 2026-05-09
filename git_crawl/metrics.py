from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from enum import Enum
from typing import Iterable

from .gitlog import CommitRecord
from .path_classification import GENERATED_LIKE_CLASSES, classify_path


class CommitChangesFiltrationLevel(str, Enum):
    """How aggressively to filter noisy file changes when aggregating commit statistics."""

    ALL = "all"
    NON_BINARY = "non_binary"
    SOURCE_LIKE = "source_like"


def _keep_change(change, level):
    if level == CommitChangesFiltrationLevel.ALL:
        return True
    if change.is_binary:
        return False
    if level == CommitChangesFiltrationLevel.NON_BINARY:
        return True
    classification = classify_path(change.path, is_binary=change.is_binary)
    return classification.path_class not in GENERATED_LIKE_CLASSES


def filter_commit_changes(commits, level):
    """Return a copy of commits with file changes filtered by the given level."""
    result = []
    for commit in commits:
        kept = [c for c in commit.changes if _keep_change(c, level)]
        result.append(
            CommitRecord(
                repo=commit.repo,
                sha=commit.sha,
                author_name=commit.author_name,
                author_email=commit.author_email,
                author_login=commit.author_login,
                authored_at=commit.authored_at,
                parents=commit.parents,
                changes=kept,
            )
        )
    return result


@dataclass(frozen=True)
class RepoDayMetrics:
    org: str
    repo: str
    date: str
    commits: int
    unique_contributors: int
    lines_added: int
    lines_deleted: int
    files_changed: int


@dataclass(frozen=True)
class ContributorDayMetrics:
    org: str
    repo: str
    date: str
    author_name: str
    author_email: str
    author_login: str | None
    commits: int
    lines_added: int
    lines_deleted: int
    files_changed: int


@dataclass(frozen=True)
class OrgDayMetrics:
    org: str
    date: str
    commits: int
    unique_contributors: int
    lines_added: int
    lines_deleted: int
    files_changed: int


@dataclass(frozen=True)
class AggregateResult:
    repo_days: list[RepoDayMetrics]
    contributor_days: list[ContributorDayMetrics]
    org_days: list[OrgDayMetrics]


def _normalized_email(email: str) -> str:
    return email.strip().lower()


def _normalized_login(login: str | None) -> str | None:
    if login is None:
        return None
    stripped = login.strip()
    return stripped.lower() if stripped else None


def _contributor_identity(commit: CommitRecord) -> str:
    login = _normalized_login(commit.author_login)
    if login:
        return f"login:{login}"
    email = _normalized_email(commit.author_email)
    if email:
        return f"email:{email}"
    return f"name:{commit.author_name.strip()}"


def aggregate_daily(org: str, commits: Iterable[CommitRecord]) -> AggregateResult:
    """Aggregate parsed commit records into daily org, repo, and contributor rows."""
    repo_acc: dict[tuple[str, str], dict[str, object]] = {}
    contributor_acc: dict[tuple[str, str, str], dict[str, object]] = {}
    org_acc: dict[str, dict[str, object]] = {}

    for commit in commits:
        day = commit.authored_at.astimezone(UTC).date().isoformat()
        additions = sum(change.additions for change in commit.changes)
        deletions = sum(change.deletions for change in commit.changes)
        files_changed = len(commit.changes)

        repo_key = (commit.repo, day)
        repo_bucket = repo_acc.setdefault(
            repo_key,
            {
                "commits": set(),
                "contributors": set(),
                "lines_added": 0,
                "lines_deleted": 0,
                "files_changed": 0,
            },
        )
        repo_bucket["commits"].add(commit.sha)  # type: ignore[union-attr]
        repo_bucket["contributors"].add(_contributor_identity(commit))  # type: ignore[union-attr]
        repo_bucket["lines_added"] += additions  # type: ignore[operator]
        repo_bucket["lines_deleted"] += deletions  # type: ignore[operator]
        repo_bucket["files_changed"] += files_changed  # type: ignore[operator]

        contributor_key = (commit.repo, day, _contributor_identity(commit))
        contributor_bucket = contributor_acc.setdefault(
            contributor_key,
            {
                "author_name": commit.author_name,
                "author_email": _normalized_email(commit.author_email),
                "author_login": _normalized_login(commit.author_login),
                "commits": set(),
                "lines_added": 0,
                "lines_deleted": 0,
                "files_changed": 0,
            },
        )
        contributor_bucket["commits"].add(commit.sha)  # type: ignore[union-attr]
        contributor_bucket["lines_added"] += additions  # type: ignore[operator]
        contributor_bucket["lines_deleted"] += deletions  # type: ignore[operator]
        contributor_bucket["files_changed"] += files_changed  # type: ignore[operator]

        org_bucket = org_acc.setdefault(
            day,
            {
                "commits": set(),
                "contributors": set(),
                "lines_added": 0,
                "lines_deleted": 0,
                "files_changed": 0,
            },
        )
        org_bucket["commits"].add((commit.repo, commit.sha))  # type: ignore[union-attr]
        org_bucket["contributors"].add(_contributor_identity(commit))  # type: ignore[union-attr]
        org_bucket["lines_added"] += additions  # type: ignore[operator]
        org_bucket["lines_deleted"] += deletions  # type: ignore[operator]
        org_bucket["files_changed"] += files_changed  # type: ignore[operator]

    repo_days = [
        RepoDayMetrics(
            org=org,
            repo=repo,
            date=day,
            commits=len(bucket["commits"]),  # type: ignore[arg-type]
            unique_contributors=len(bucket["contributors"]),  # type: ignore[arg-type]
            lines_added=int(bucket["lines_added"]),
            lines_deleted=int(bucket["lines_deleted"]),
            files_changed=int(bucket["files_changed"]),
        )
        for (repo, day), bucket in repo_acc.items()
    ]

    contributor_days = [
        ContributorDayMetrics(
            org=org,
            repo=repo,
            date=day,
            author_name=str(bucket["author_name"]),
            author_email=str(bucket["author_email"]),
            author_login=(
                str(bucket["author_login"])
                if bucket["author_login"] is not None
                else None
            ),
            commits=len(bucket["commits"]),  # type: ignore[arg-type]
            lines_added=int(bucket["lines_added"]),
            lines_deleted=int(bucket["lines_deleted"]),
            files_changed=int(bucket["files_changed"]),
        )
        for (repo, day, _identity), bucket in contributor_acc.items()
    ]

    org_days = [
        OrgDayMetrics(
            org=org,
            date=day,
            commits=len(bucket["commits"]),  # type: ignore[arg-type]
            unique_contributors=len(bucket["contributors"]),  # type: ignore[arg-type]
            lines_added=int(bucket["lines_added"]),
            lines_deleted=int(bucket["lines_deleted"]),
            files_changed=int(bucket["files_changed"]),
        )
        for day, bucket in org_acc.items()
    ]

    return AggregateResult(
        repo_days=sorted(repo_days, key=lambda row: (row.repo, row.date)),
        contributor_days=sorted(
            contributor_days,
            key=lambda row: (row.repo, row.date, row.author_email, row.author_login or "", row.author_name),
        ),
        org_days=sorted(org_days, key=lambda row: row.date),
    )
