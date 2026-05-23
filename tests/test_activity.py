from datetime import datetime, timezone

from git_crawl.activity import build_activity
from git_crawl.gitlog import CommitRecord, FileChange


def _commit(sha, author, email, when, changes):
    return CommitRecord(
        repo="api",
        sha=sha,
        author_name=author,
        author_email=email,
        author_login=None,
        authored_at=when,
        parents=[],
        changes=changes,
    )


def test_build_activity_counts_credited_source_like_changes_and_reports_skipped_noise():
    commits = [
        _commit(
            "mixed",
            "Alice",
            "alice@example.com",
            datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc),
            [
                FileChange(10, 2, "src/app.py", False),
                FileChange(100, 10, "package-lock.json", False),
                FileChange(6, 1, "generated/client.py", False),
                FileChange(5, 1, "vendor/lib.py", False),
                FileChange(20, 3, "api/schema.yaml", False),
                FileChange(0, 0, "assets/logo.png", True),
            ],
        ),
        _commit(
            "lockfile-only",
            "Bob",
            "bob@example.com",
            datetime(2026, 5, 5, 9, 0, tzinfo=timezone.utc),
            [FileChange(7, 1, "web/yarn.lock", False)],
        ),
    ]

    activity = build_activity(
        org="chutesai",
        run_id="run-1",
        status="success",
        ref_scope="default-branch",
        history_since=None,
        history_until=None,
        commits=commits,
    )

    assert activity["schema_version"] == "git-crawl-activity-v1"
    assert activity["filter"] == {
        "mode": "source_like",
        "excluded_reasons": [
            "binary",
            "lockfile",
            "generated",
            "vendored",
            "spec/schema-like",
        ],
    }
    assert activity["totals"] == {
        "commits": 1,
        "file_changes": 1,
        "lines_added": 10,
        "lines_deleted": 2,
        "active_days": 1,
        "repo_days": 1,
        "contributor_days": 1,
        "distinct_contributors": 1,
    }
    assert activity["averages"]["per_active_day"] == {
        "commits": 1.0,
        "file_changes": 1.0,
        "lines_added": 10.0,
        "lines_deleted": 2.0,
    }
    assert activity["skipped"] == {
        "file_changes": 6,
        "lines_added": 138,
        "lines_deleted": 16,
        "by_reason": {
            "binary": {"file_changes": 1, "lines_added": 0, "lines_deleted": 0},
            "lockfile": {"file_changes": 2, "lines_added": 107, "lines_deleted": 11},
            "generated": {"file_changes": 1, "lines_added": 6, "lines_deleted": 1},
            "vendored": {"file_changes": 1, "lines_added": 5, "lines_deleted": 1},
            "spec/schema-like": {"file_changes": 1, "lines_added": 20, "lines_deleted": 3},
        },
    }
