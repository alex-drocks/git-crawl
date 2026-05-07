from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .gitlog import CommitRecord
from .path_classification import classify_path


@dataclass(frozen=True)
class CommitRow:
    run_id: str
    org: str
    repo: str
    sha: str
    parents: str
    parent_count: int
    is_merge_commit: bool
    author_name: str
    author_email: str
    author_login: str | None
    authored_at: str
    files_changed: int
    lines_added: int
    lines_deleted: int


@dataclass(frozen=True)
class FileChangeRow:
    run_id: str
    org: str
    repo: str
    sha: str
    path: str
    additions: int
    deletions: int
    is_binary: bool
    path_class: str = "unknown"
    is_generated_like: bool = False
    is_lockfile: bool = False

    def __post_init__(self) -> None:
        if self.path_class != "unknown" or self.is_generated_like or self.is_lockfile:
            return
        classification = classify_path(self.path, is_binary=self.is_binary)
        object.__setattr__(self, "path_class", classification.path_class)
        object.__setattr__(self, "is_generated_like", classification.is_generated_like)
        object.__setattr__(self, "is_lockfile", classification.is_lockfile)


def build_raw_rows(
    *,
    org: str,
    run_id: str,
    commits: Iterable[CommitRecord],
) -> tuple[list[CommitRow], list[FileChangeRow]]:
    """Normalize parsed commits into stable raw commit and file-change rows."""
    commit_rows: list[CommitRow] = []
    file_change_rows: list[FileChangeRow] = []

    for commit in commits:
        lines_added = sum(change.additions for change in commit.changes)
        lines_deleted = sum(change.deletions for change in commit.changes)
        files_changed = len(commit.changes)
        commit_rows.append(
            CommitRow(
                run_id=run_id,
                org=org,
                repo=commit.repo,
                sha=commit.sha,
                parents=" ".join(commit.parents),
                parent_count=len(commit.parents),
                is_merge_commit=len(commit.parents) > 1,
                author_name=commit.author_name,
                author_email=commit.author_email,
                author_login=commit.author_login,
                authored_at=commit.authored_at.isoformat(),
                files_changed=files_changed,
                lines_added=lines_added,
                lines_deleted=lines_deleted,
            )
        )
        for change in commit.changes:
            classification = classify_path(change.path, is_binary=change.is_binary)
            file_change_rows.append(
                FileChangeRow(
                    run_id=run_id,
                    org=org,
                    repo=commit.repo,
                    sha=commit.sha,
                    path=change.path,
                    additions=change.additions,
                    deletions=change.deletions,
                    is_binary=change.is_binary,
                    path_class=classification.path_class,
                    is_generated_like=classification.is_generated_like,
                    is_lockfile=classification.is_lockfile,
                )
            )

    return commit_rows, file_change_rows
