import json

from git_crawl.github import RepoInfo
from git_crawl.metrics import AggregateResult, ContributorDayMetrics, OrgDayMetrics, RepoDayMetrics
from git_crawl.output import rows_to_dicts, write_csv, write_jsonl
from git_crawl.pipeline import CrawlResult, build_crawl_summary, write_crawl_outputs
from git_crawl.raw import CommitRow, FileChangeRow
from git_crawl.state import CrawlRunRecord


def test_structured_outputs_are_stable_jsonl_and_csv(tmp_path):
    rows = [
        RepoDayMetrics(
            org="chutesai",
            repo="api",
            date="2026-05-04",
            commits=2,
            unique_contributors=1,
            lines_added=12,
            lines_deleted=3,
            files_changed=4,
        )
    ]

    assert rows_to_dicts(rows) == [
        {
            "org": "chutesai",
            "repo": "api",
            "date": "2026-05-04",
            "commits": 2,
            "unique_contributors": 1,
            "lines_added": 12,
            "lines_deleted": 3,
            "files_changed": 4,
        }
    ]

    jsonl_path = tmp_path / "repo_days.jsonl"
    csv_path = tmp_path / "repo_days.csv"
    write_jsonl(jsonl_path, rows)
    write_csv(csv_path, rows)

    assert [json.loads(line) for line in jsonl_path.read_text().splitlines()] == rows_to_dicts(rows)
    assert csv_path.read_text().splitlines() == [
        "org,repo,date,commits,unique_contributors,lines_added,lines_deleted,files_changed",
        "chutesai,api,2026-05-04,2,1,12,3,4",
    ]


def test_write_crawl_outputs_includes_org_days_and_run_scoped_repositories(tmp_path):
    run = CrawlRunRecord(
        run_id="run-1",
        org="chutesai",
        started_at="2026-05-04T00:00:00+00:00",
        finished_at="2026-05-04T00:01:00+00:00",
        status="success",
        ref_scope="default-branch",
        history_since="2026-01-01",
        history_until=None,
        active_since=None,
        repositories_discovered=1,
        repositories_selected=1,
        repositories_crawled=1,
        repositories_failed=0,
        commits_parsed=1,
        error_message=None,
    )
    repo = RepoInfo(
        name="api",
        full_name="chutesai/api",
        clone_url="https://github.com/chutesai/api.git",
        ssh_url="git@github.com:chutesai/api.git",
        default_branch="main",
        pushed_at="2026-05-04T00:00:00Z",
        archived=False,
        fork=False,
        private=False,
        language="Python",
    )
    result = CrawlResult(
        org="chutesai",
        run=run,
        repositories=[repo],
        commits=[],
        raw_commits=[
            CommitRow(
                run_id="run-1",
                org="chutesai",
                repo="api",
                sha="abc123",
                parents="",
                parent_count=0,
                is_merge_commit=False,
                author_name="Alice",
                author_email="alice@example.com",
                author_login=None,
                authored_at="2026-05-04T10:00:00+00:00",
                files_changed=1,
                lines_added=3,
                lines_deleted=1,
            )
        ],
        file_changes=[
            FileChangeRow(
                run_id="run-1",
                org="chutesai",
                repo="api",
                sha="abc123",
                path="src/app.py",
                additions=3,
                deletions=1,
                is_binary=False,
            )
        ],
        failed_repositories=[],
        repo_state_updates=[],
        aggregates=AggregateResult(
            repo_days=[
                RepoDayMetrics(
                    org="chutesai",
                    repo="api",
                    date="2026-05-04",
                    commits=1,
                    unique_contributors=1,
                    lines_added=3,
                    lines_deleted=1,
                    files_changed=1,
                )
            ],
            contributor_days=[
                ContributorDayMetrics(
                    org="chutesai",
                    repo="api",
                    date="2026-05-04",
                    author_name="Alice",
                    author_email="alice@example.com",
                    author_login=None,
                    commits=1,
                    lines_added=3,
                    lines_deleted=1,
                    files_changed=1,
                )
            ],
            org_days=[
                OrgDayMetrics(
                    org="chutesai",
                    date="2026-05-04",
                    commits=1,
                    unique_contributors=1,
                    lines_added=3,
                    lines_deleted=1,
                    files_changed=1,
                )
            ],
        ),
    )

    written = write_crawl_outputs(result, tmp_path, write_json=True, write_csv_files=True)

    assert tmp_path / "org_days.jsonl" in written
    assert tmp_path / "org_days.csv" in written
    assert tmp_path / "excluded_repositories.jsonl" in written
    assert tmp_path / "excluded_repositories.csv" in written
    assert tmp_path / "summary.json" in written
    assert tmp_path / "summary.md" in written
    assert tmp_path / "output_manifest.json" in written
    assert [json.loads(line) for line in (tmp_path / "org_days.jsonl").read_text().splitlines()] == [
        {
            "run_id": "run-1",
            "org": "chutesai",
            "date": "2026-05-04",
            "commits": 1,
            "unique_contributors": 1,
            "lines_added": 3,
            "lines_deleted": 1,
            "files_changed": 1,
        }
    ]
    assert [json.loads(line) for line in (tmp_path / "repo_days.jsonl").read_text().splitlines()] == [
        {
            "run_id": "run-1",
            "org": "chutesai",
            "repo": "api",
            "date": "2026-05-04",
            "commits": 1,
            "unique_contributors": 1,
            "lines_added": 3,
            "lines_deleted": 1,
            "files_changed": 1,
        }
    ]
    assert [json.loads(line) for line in (tmp_path / "contributor_days.jsonl").read_text().splitlines()] == [
        {
            "run_id": "run-1",
            "org": "chutesai",
            "repo": "api",
            "date": "2026-05-04",
            "author_name": "Alice",
            "author_email": "alice@example.com",
            "author_login": None,
            "commits": 1,
            "lines_added": 3,
            "lines_deleted": 1,
            "files_changed": 1,
        }
    ]
    repositories = [json.loads(line) for line in (tmp_path / "repositories.jsonl").read_text().splitlines()]
    assert repositories == [
        {
            "run_id": "run-1",
            "org": "chutesai",
            "name": "api",
            "full_name": "chutesai/api",
            "clone_url": "https://github.com/chutesai/api.git",
            "ssh_url": "git@github.com:chutesai/api.git",
            "default_branch": "main",
            "pushed_at": "2026-05-04T00:00:00Z",
            "archived": False,
            "fork": False,
            "private": False,
            "language": "Python",
        }
    ]
    file_changes = [json.loads(line) for line in (tmp_path / "file_changes.jsonl").read_text().splitlines()]
    assert file_changes[0]["path_class"] == "source"
    assert file_changes[0]["is_generated_like"] is False
    assert file_changes[0]["is_lockfile"] is False

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["schema_version"] == "git-crawl-summary-v1"
    assert summary["output_schema_version"] == "git-crawl-output-v1"
    assert summary["org"] == "chutesai"
    assert summary["totals"]["commits"] == 1
    assert summary["totals"]["lines_added"] == 3
    assert summary["repositories"]["selected"] == 1
    assert summary["repositories"]["excluded"] == 0
    summary_md = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "raw git churn" in summary_md
    assert "Calendar averages" in summary_md
    assert "Per calendar day" in summary_md

    manifest = json.loads((tmp_path / "output_manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == "git-crawl-output-manifest-v1"
    assert manifest["output_schema_version"] == "git-crawl-output-v1"
    assert manifest["run"] == {"run_id": "run-1", "status": "success", "target": "chutesai"}
    assert manifest["datasets"]["commits"] == {
        "schema_version": "git-crawl-commits-v1",
        "jsonl": "commits.jsonl",
        "csv": "commits.csv",
        "fields": [
            "run_id",
            "org",
            "repo",
            "sha",
            "parents",
            "parent_count",
            "is_merge_commit",
            "author_name",
            "author_email",
            "author_login",
            "authored_at",
            "files_changed",
            "lines_added",
            "lines_deleted",
        ],
    }
    assert manifest["datasets"]["summary"] == {
        "schema_version": "git-crawl-summary-v1",
        "json": "summary.json",
        "fields": None,
    }


def test_crawl_summary_includes_calendar_average_rates_for_sparse_date_range():
    run = CrawlRunRecord(
        run_id="run-1",
        org="chutesai",
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-02-01T00:00:00+00:00",
        status="success",
        ref_scope="default-branch",
        history_since=None,
        history_until=None,
        active_since=None,
        repositories_discovered=1,
        repositories_selected=1,
        repositories_crawled=1,
        repositories_failed=0,
        commits_parsed=32,
        error_message=None,
    )
    raw_commits = [
        CommitRow(
            run_id="run-1",
            org="chutesai",
            repo="api",
            sha=f"sha-{index}",
            parents="",
            parent_count=0,
            is_merge_commit=False,
            author_name="Alice",
            author_email="alice@example.com",
            author_login=None,
            authored_at=(
                "2026-01-01T10:00:00+00:00" if index < 16 else "2026-02-01T10:00:00+00:00"
            ),
            files_changed=1,
            lines_added=10,
            lines_deleted=2,
        )
        for index in range(32)
    ]
    file_changes = [
        FileChangeRow(
            run_id="run-1",
            org="chutesai",
            repo="api",
            sha=commit.sha,
            path=f"src/{commit.sha}.py",
            additions=10,
            deletions=2,
            is_binary=False,
        )
        for commit in raw_commits
    ]
    result = CrawlResult(
        org="chutesai",
        run=run,
        repositories=[],
        commits=[],
        raw_commits=raw_commits,
        file_changes=file_changes,
        failed_repositories=[],
        repo_state_updates=[],
        aggregates=AggregateResult(
            repo_days=[],
            contributor_days=[],
            org_days=[
                OrgDayMetrics(
                    org="chutesai",
                    date="2026-01-01",
                    commits=16,
                    unique_contributors=1,
                    lines_added=160,
                    lines_deleted=32,
                    files_changed=16,
                ),
                OrgDayMetrics(
                    org="chutesai",
                    date="2026-02-01",
                    commits=16,
                    unique_contributors=1,
                    lines_added=160,
                    lines_deleted=32,
                    files_changed=16,
                ),
            ],
        ),
    )

    summary = build_crawl_summary(result)

    assert summary["calendar_span"] == {"days": 32, "weeks": 5, "months": 2}
    assert summary["averages"]["per_calendar_day"] == {
        "commits": 1.0,
        "file_changes": 1.0,
        "lines_added": 10.0,
        "lines_deleted": 2.0,
    }
    assert summary["averages"]["per_calendar_week"] == {
        "commits": 6.4,
        "file_changes": 6.4,
        "lines_added": 64.0,
        "lines_deleted": 12.8,
    }
    assert summary["averages"]["per_calendar_month"] == {
        "commits": 16.0,
        "file_changes": 16.0,
        "lines_added": 160.0,
        "lines_deleted": 32.0,
    }


def test_write_csv_escapes_spreadsheet_formula_values(tmp_path):
    csv_path = tmp_path / "authors.csv"

    write_csv(csv_path, [{"author_name": "=1+1", "path": "@cmd"}], fieldnames=["author_name", "path"])

    assert csv_path.read_text(encoding="utf-8").splitlines() == [
        "author_name,path",
        "'=1+1,'@cmd",
    ]


def test_write_crawl_outputs_redacts_credentials_from_repository_urls(tmp_path):
    run = CrawlRunRecord(
        run_id="run-1",
        org="chutesai",
        started_at="2026-05-04T00:00:00+00:00",
        finished_at="2026-05-04T00:01:00+00:00",
        status="success",
        ref_scope="default-branch",
        history_since=None,
        history_until=None,
        active_since=None,
        repositories_discovered=1,
        repositories_selected=1,
        repositories_crawled=1,
        repositories_failed=0,
        commits_parsed=0,
        error_message=None,
    )
    result = CrawlResult(
        org="chutesai",
        run=run,
        repositories=[
            RepoInfo(
                name="api",
                full_name="chutesai/api",
                clone_url="https://sensitive-userinfo@github.com/chutesai/api.git",
                ssh_url="ssh://sensitive-userinfo@github.com/chutesai/api.git",
                default_branch="main",
                pushed_at="2026-05-04T00:00:00Z",
                archived=False,
                fork=False,
                private=False,
                language="Python",
            )
        ],
        commits=[],
        raw_commits=[],
        file_changes=[],
        failed_repositories=[],
        repo_state_updates=[],
        aggregates=AggregateResult(repo_days=[], contributor_days=[], org_days=[]),
    )

    write_crawl_outputs(result, tmp_path, write_json=True, write_csv_files=False)

    repository = json.loads((tmp_path / "repositories.jsonl").read_text(encoding="utf-8"))
    assert "sensitive-userinfo" not in repository["clone_url"]
    assert "sensitive-userinfo" not in repository["ssh_url"]
    assert repository["clone_url"] == "https://[REDACTED]@github.com/chutesai/api.git"
    assert repository["ssh_url"] == "ssh://[REDACTED]@github.com/chutesai/api.git"
