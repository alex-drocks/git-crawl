from datetime import datetime, timezone

from git_crawl.gitlog import CommitRecord, FileChange
from git_crawl.raw import build_raw_rows


def test_build_raw_rows_normalizes_commits_and_file_changes_for_outputs():
    commit = CommitRecord(
        repo="api",
        sha="abc123",
        author_name="Alice Example",
        author_email="12345+alice@users.noreply.github.com",
        author_login="alice",
        authored_at=datetime(2026, 5, 4, 10, 15, tzinfo=timezone.utc),
        parents=["parent1", "parent2"],
        changes=[
            FileChange(additions=10, deletions=2, path="src/app.py", is_binary=False),
            FileChange(additions=0, deletions=0, path="assets/logo.png", is_binary=True),
        ],
    )

    commit_rows, file_change_rows = build_raw_rows(
        org="chutesai",
        run_id="run-1",
        commits=[commit],
    )

    assert len(commit_rows) == 1
    assert commit_rows[0].run_id == "run-1"
    assert commit_rows[0].org == "chutesai"
    assert commit_rows[0].repo == "api"
    assert commit_rows[0].sha == "abc123"
    assert commit_rows[0].parents == "parent1 parent2"
    assert commit_rows[0].parent_count == 2
    assert commit_rows[0].is_merge_commit is True
    assert commit_rows[0].author_login == "alice"
    assert commit_rows[0].authored_at == "2026-05-04T10:15:00+00:00"
    assert commit_rows[0].files_changed == 2
    assert commit_rows[0].lines_added == 10
    assert commit_rows[0].lines_deleted == 2

    assert [
        (
            row.sha,
            row.path,
            row.additions,
            row.deletions,
            row.is_binary,
            row.path_class,
            row.is_generated_like,
            row.is_lockfile,
        )
        for row in file_change_rows
    ] == [
        ("abc123", "src/app.py", 10, 2, False, "source", False, False),
        ("abc123", "assets/logo.png", 0, 0, True, "binary", False, False),
    ]
    assert all(row.run_id == "run-1" and row.org == "chutesai" and row.repo == "api" for row in file_change_rows)
