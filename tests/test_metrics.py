from datetime import datetime, timedelta, timezone

from git_crawl.gitlog import CommitRecord, FileChange
from git_crawl.metrics import aggregate_daily


def _commit(sha, repo, author, email, when, changes):
    return CommitRecord(
        repo=repo,
        sha=sha,
        author_name=author,
        author_email=email,
        author_login=None,
        authored_at=when,
        parents=[],
        changes=changes,
    )


def test_aggregate_daily_builds_repo_and_contributor_rows_without_double_counting_commits():
    records = [
        _commit(
            "a1",
            "api",
            "Alice",
            "alice@example.com",
            datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc),
            [FileChange(10, 2, "a.py", False), FileChange(5, 0, "b.py", False)],
        ),
        _commit(
            "a2",
            "api",
            "Alice",
            "alice@example.com",
            datetime(2026, 5, 4, 15, 0, tzinfo=timezone.utc),
            [FileChange(1, 1, "a.py", False)],
        ),
        _commit(
            "b1",
            "api",
            "Bob",
            "bob@example.com",
            datetime(2026, 5, 4, 16, 0, tzinfo=timezone.utc),
            [FileChange(0, 0, "logo.png", True)],
        ),
        _commit(
            "c1",
            "web",
            "Carol",
            "carol@example.com",
            datetime(2026, 5, 5, 1, 0, tzinfo=timezone.utc),
            [FileChange(7, 3, "index.ts", False)],
        ),
    ]

    result = aggregate_daily(org="chutesai", commits=records)

    repo_rows = {(row.repo, row.date): row for row in result.repo_days}
    api_row = repo_rows[("api", "2026-05-04")]
    assert api_row.org == "chutesai"
    assert api_row.commits == 3
    assert api_row.unique_contributors == 2
    assert api_row.lines_added == 16
    assert api_row.lines_deleted == 3
    assert api_row.files_changed == 4

    contributor_rows = {
        (row.repo, row.date, row.author_email): row for row in result.contributor_days
    }
    alice_row = contributor_rows[("api", "2026-05-04", "alice@example.com")]
    assert alice_row.commits == 2
    assert alice_row.lines_added == 16
    assert alice_row.lines_deleted == 3
    assert alice_row.files_changed == 3
    assert alice_row.author_login is None

    bob_row = contributor_rows[("api", "2026-05-04", "bob@example.com")]
    assert bob_row.commits == 1
    assert bob_row.lines_added == 0
    assert bob_row.lines_deleted == 0
    assert bob_row.files_changed == 1

    org_rows = {row.date: row for row in result.org_days}
    org_row = org_rows["2026-05-04"]
    assert org_row.org == "chutesai"
    assert org_row.commits == 3
    assert org_row.unique_contributors == 2
    assert org_row.lines_added == 16
    assert org_row.lines_deleted == 3
    assert org_row.files_changed == 4


def test_aggregate_daily_counts_org_contributors_once_across_repositories():
    records = [
        _commit(
            "api1",
            "api",
            "Alice",
            "alice@example.com",
            datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc),
            [FileChange(10, 1, "api.py", False)],
        ),
        _commit(
            "web1",
            "web",
            "Alice",
            "alice@example.com",
            datetime(2026, 5, 4, 10, 0, tzinfo=timezone.utc),
            [FileChange(20, 2, "web.ts", False)],
        ),
    ]

    result = aggregate_daily(org="chutesai", commits=records)

    assert len(result.repo_days) == 2
    assert len(result.org_days) == 1
    org_row = result.org_days[0]
    assert org_row.org == "chutesai"
    assert org_row.date == "2026-05-04"
    assert org_row.commits == 2
    assert org_row.unique_contributors == 1
    assert org_row.lines_added == 30
    assert org_row.lines_deleted == 3
    assert org_row.files_changed == 2


def test_aggregate_daily_buckets_author_timestamps_by_utc_date():
    records = [
        _commit(
            "late",
            "api",
            "Alice",
            "alice@example.com",
            datetime(2026, 5, 4, 23, 30, tzinfo=timezone(timedelta(hours=-5))),
            [FileChange(1, 0, "a.py", False)],
        )
    ]

    result = aggregate_daily(org="chutesai", commits=records)

    assert result.repo_days[0].date == "2026-05-05"
    assert result.contributor_days[0].date == "2026-05-05"
    assert result.org_days[0].date == "2026-05-05"


def test_aggregate_daily_keeps_empty_email_contributors_separate_by_name():
    records = [
        _commit(
            "alice",
            "api",
            "Alice",
            "",
            datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc),
            [FileChange(1, 0, "alice.py", False)],
        ),
        _commit(
            "bob",
            "api",
            "Bob",
            "",
            datetime(2026, 5, 4, 10, 0, tzinfo=timezone.utc),
            [FileChange(2, 0, "bob.py", False)],
        ),
    ]

    result = aggregate_daily(org="chutesai", commits=records)

    assert result.repo_days[0].unique_contributors == 2
    assert result.org_days[0].unique_contributors == 2
    assert [(row.author_name, row.commits) for row in result.contributor_days] == [("Alice", 1), ("Bob", 1)]


def test_aggregate_daily_normalizes_author_email_case_for_contributor_identity():
    records = [
        _commit(
            "upper",
            "api",
            "Kyle",
            "Kyle.Widmann@gmail.com",
            datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc),
            [FileChange(1, 0, "a.py", False)],
        ),
        _commit(
            "lower",
            "api",
            "Kyle",
            "kyle.widmann@gmail.com",
            datetime(2026, 5, 4, 10, 0, tzinfo=timezone.utc),
            [FileChange(2, 0, "b.py", False)],
        ),
    ]

    result = aggregate_daily(org="chutesai", commits=records)

    assert result.repo_days[0].unique_contributors == 1
    assert result.org_days[0].unique_contributors == 1
    assert len(result.contributor_days) == 1
    contributor = result.contributor_days[0]
    assert contributor.author_email == "kyle.widmann@gmail.com"
    assert contributor.commits == 2
    assert contributor.lines_added == 3
