import json
from datetime import datetime, timezone

import pytest


def test_publish_static_api_copies_outputs_and_writes_fetchable_indexes(tmp_path):
    from git_crawl.static_api import publish_static_api

    data_dir = tmp_path / "crawl-out"
    site_dir = tmp_path / "site"
    data_dir.mkdir()
    (data_dir / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "org": "chutesai",
                "status": "success",
                "ref_scope": "default-branch",
                "history_since": None,
                "history_until": None,
                "active_since": None,
                "totals": {"commits": 2, "file_changes": 3},
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "org_days.jsonl").write_text('{"day":"2026-05-06","commits":2}\n', encoding="utf-8")
    (data_dir / "repositories.csv").write_text("org,name\nchutesai,api\n", encoding="utf-8")
    (data_dir / "output_manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": "git-crawl-output-manifest-v1",
                "output_schema_version": "git-crawl-output-v1",
                "datasets": {},
            }
        ),
        encoding="utf-8",
    )
    stale_target = site_dir / "chutesai" / "latest" / "stale.json"
    stale_target.parent.mkdir(parents=True)
    stale_target.write_text("stale", encoding="utf-8")

    result = publish_static_api(
        org="chutesai",
        data_dir=data_dir,
        site_dir=site_dir,
        base_url="https://alex-drocks.github.io/git-crawl",
        generated_at=datetime(2026, 5, 6, tzinfo=timezone.utc),
    )

    assert result.dataset_dir == site_dir / "chutesai" / "latest"
    assert sorted(path.name for path in result.copied_files) == [
        "org_days.jsonl",
        "output_manifest.json",
        "repositories.csv",
        "summary.json",
    ]
    assert (site_dir / "chutesai" / "latest" / "summary.json").is_file()
    assert (site_dir / "chutesai" / "latest" / "org_days.jsonl").is_file()
    assert not stale_target.exists()

    latest = json.loads((site_dir / "api" / "chutesai" / "latest.json").read_text(encoding="utf-8"))
    assert latest["api_version"] == 1
    assert latest["output_schema_version"] == "git-crawl-output-v1"
    assert latest["org"] == "chutesai"
    assert latest["run_label"] == "latest"
    assert latest["generated_at"] == "2026-05-06T00:00:00+00:00"
    assert latest["run"] == {
        "run_id": "run-1",
        "status": "success",
        "ref_scope": "default-branch",
        "history_since": None,
        "history_until": None,
        "active_since": None,
    }
    assert latest["summary"] == {
        "path": "/chutesai/latest/summary.json",
        "url": "https://alex-drocks.github.io/git-crawl/chutesai/latest/summary.json",
    }
    assert latest["output_manifest"] == {
        "path": "/chutesai/latest/output_manifest.json",
        "url": "https://alex-drocks.github.io/git-crawl/chutesai/latest/output_manifest.json",
    }
    assert latest["files"]["org_days.jsonl"] == {
        "format": "jsonl",
        "path": "/chutesai/latest/org_days.jsonl",
        "url": "https://alex-drocks.github.io/git-crawl/chutesai/latest/org_days.jsonl",
        "bytes": len('{"day":"2026-05-06","commits":2}\n'.encode()),
    }

    root_index = json.loads((site_dir / "index.json").read_text(encoding="utf-8"))
    assert root_index["orgs"]["chutesai"]["latest"] == {
        "path": "/api/chutesai/latest.json",
        "url": "https://alex-drocks.github.io/git-crawl/api/chutesai/latest.json",
    }
    assert json.loads((site_dir / "api" / "index.json").read_text(encoding="utf-8")) == root_index


def test_publish_static_api_writes_user_friendly_kpi_dashboard(tmp_path):
    from git_crawl.static_api import publish_static_api

    data_dir = tmp_path / "crawl-out"
    site_dir = tmp_path / "site"
    data_dir.mkdir()
    (data_dir / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "org": "chutesai",
                "status": "success",
                "ref_scope": "default-branch",
                "history_since": "2026-01-01",
                "history_until": None,
                "active_since": "2025-01-01T00:00:00Z",
                "repositories": {
                    "discovered": 9,
                    "selected": 6,
                    "crawled": 6,
                    "failed": 0,
                    "excluded": 3,
                    "excluded_by_reason": {"fork": 2, "archived": 1},
                },
                "totals": {
                    "commits": 42,
                    "file_changes": 87,
                    "lines_added": 1234,
                    "lines_deleted": 321,
                    "active_days": 11,
                    "repo_days": 18,
                    "contributor_days": 27,
                    "distinct_contributor_keys": 5,
                    "first_day": "2026-01-02",
                    "last_day": "2026-02-14",
                },
                "calendar_span": {"days": 44, "weeks": 7, "months": 2},
                "averages": {
                    "per_calendar_day": {
                        "commits": 0.95,
                        "file_changes": 1.98,
                        "lines_added": 28.05,
                        "lines_deleted": 7.3,
                    },
                    "per_calendar_week": {
                        "commits": 6.0,
                        "file_changes": 12.43,
                        "lines_added": 176.29,
                        "lines_deleted": 45.86,
                    },
                    "per_calendar_month": {
                        "commits": 21.0,
                        "file_changes": 43.5,
                        "lines_added": 617.0,
                        "lines_deleted": 160.5,
                    },
                },
                "source_like_totals": {"file_changes": 70, "lines_added": 1012, "lines_deleted": 275},
                "generated_like_totals": {"file_changes": 17, "lines_added": 222, "lines_deleted": 46},
                "path_classes": {
                    "source": {"files_changed": 60, "lines_added": 900, "lines_deleted": 250},
                    "lockfile": {"files_changed": 17, "lines_added": 222, "lines_deleted": 46},
                },
                "top_repositories_by_commits": [
                    {"repo": "api", "commits": 31, "files_changed": 68, "lines_added": 980, "lines_deleted": 210},
                    {"repo": "worker", "commits": 11, "files_changed": 19, "lines_added": 254, "lines_deleted": 111},
                ],
                "top_paths_by_lines_added": [
                    {
                        "repo": "api",
                        "path": "src/server.py",
                        "path_class": "source",
                        "files_changed": 4,
                        "lines_added": 420,
                        "lines_deleted": 36,
                    }
                ],
                "caveats": ["Line counts are raw git churn from git log --numstat, not current source LOC."],
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "org_days.jsonl").write_text("{}\n", encoding="utf-8")
    (data_dir / "repo_days.jsonl").write_text("{}\n", encoding="utf-8")

    result = publish_static_api(
        org="chutesai",
        data_dir=data_dir,
        site_dir=site_dir,
        base_url="https://alex-drocks.github.io/git-crawl/",
        generated_at=datetime(2026, 5, 6, tzinfo=timezone.utc),
    )

    assert result.dashboard_files == [site_dir / "chutesai" / "latest" / "dashboard.html", site_dir / "index.html"]
    dashboard = (site_dir / "chutesai" / "latest" / "dashboard.html").read_text(encoding="utf-8")
    root_dashboard = (site_dir / "index.html").read_text(encoding="utf-8")
    latest = json.loads((site_dir / "api" / "chutesai" / "latest.json").read_text(encoding="utf-8"))

    assert latest["dashboard"] == {
        "path": "/chutesai/latest/dashboard.html",
        "url": "https://alex-drocks.github.io/git-crawl/chutesai/latest/dashboard.html",
    }
    assert "<title>chutesai KPI dashboard · git-crawl</title>" in dashboard
    assert "KPI dashboard" in dashboard
    assert "Total commits" in dashboard
    assert "42" in dashboard
    assert "Lines added" in dashboard
    assert "+1,234" in dashboard
    assert "Distinct contributors" in dashboard
    assert "5" in dashboard
    assert "Source-like additions" in dashboard
    assert "82.0%" in dashboard
    assert "api" in dashboard
    assert "<td>68</td>" in dashboard
    assert "<td>19</td>" in dashboard
    assert "src/server.py" in dashboard
    assert 'href="./summary.json"' in dashboard
    assert 'href="./org_days.jsonl"' in dashboard
    assert 'href="./repo_days.jsonl"' in dashboard
    assert 'href="./dashboard.html"' not in root_dashboard
    assert "https://alex-drocks.github.io/git-crawl/api/chutesai/latest.json" in root_dashboard


def test_publish_static_api_dashboard_uses_overflow_safe_typography(tmp_path):
    from git_crawl.static_api import publish_static_api

    data_dir = tmp_path / "crawl-out"
    site_dir = tmp_path / "site"
    data_dir.mkdir()
    (data_dir / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "c1abd81b-f70b-47af-b42b-0edd4dff98ee",
                "org": "chutesai",
                "status": "success",
                "ref_scope": "default-branch",
                "repositories": {"selected": 27, "crawled": 27, "failed": 0},
                "totals": {
                    "commits": 3508,
                    "file_changes": 14543,
                    "lines_added": 3166929,
                    "lines_deleted": 202054,
                    "active_days": 506,
                    "distinct_contributor_keys": 26,
                    "first_day": "2024-08-12",
                    "last_day": "2026-05-07",
                },
                "calendar_span": {"days": 633, "weeks": 91, "months": 22},
                "averages": {},
                "source_like_totals": {"file_changes": 10000, "lines_added": 2500000, "lines_deleted": 150000},
                "generated_like_totals": {"file_changes": 4543, "lines_added": 666929, "lines_deleted": 52054},
                "path_classes": {},
                "top_repositories_by_commits": [],
                "top_paths_by_lines_added": [],
            }
        ),
        encoding="utf-8",
    )

    publish_static_api(
        org="chutesai",
        data_dir=data_dir,
        site_dir=site_dir,
        generated_at=datetime(2026, 5, 7, 12, 57, tzinfo=timezone.utc),
    )

    dashboard = (site_dir / "chutesai" / "latest" / "dashboard.html").read_text(encoding="utf-8")
    assert '<strong class="meta-value">2026-05-07 12:57 UTC</strong>' in dashboard
    assert '<strong class="metric-value">+3,166,929</strong>' in dashboard
    assert "container-type: inline-size;" in dashboard
    assert ".metric-value" in dashboard
    assert "font-size: clamp(1.95rem, 16cqw, 2.65rem);" in dashboard
    assert "max-width: 100%;" in dashboard


def test_publish_static_api_dashboard_escapes_summary_values(tmp_path):
    from git_crawl.static_api import publish_static_api

    data_dir = tmp_path / "crawl-out"
    site_dir = tmp_path / "site"
    data_dir.mkdir()
    (data_dir / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "run-<unsafe>",
                "org": "chutesai",
                "status": "success",
                "ref_scope": "default-branch",
                "repositories": {"selected": 1, "crawled": 1, "failed": 0, "excluded": 0},
                "totals": {
                    "commits": 1,
                    "file_changes": 1,
                    "lines_added": 1,
                    "lines_deleted": 0,
                    "active_days": 1,
                    "distinct_contributor_keys": 1,
                    "first_day": "2026-01-01",
                    "last_day": "2026-01-01",
                },
                "calendar_span": {"days": 1, "weeks": 1, "months": 1},
                "averages": {},
                "source_like_totals": {"file_changes": 1, "lines_added": 1, "lines_deleted": 0},
                "generated_like_totals": {"file_changes": 0, "lines_added": 0, "lines_deleted": 0},
                "path_classes": {},
                "top_repositories_by_commits": [
                    {"repo": "api\" onclick=\"alert(1)", "commits": 1, "files_changed": 1, "lines_added": 1, "lines_deleted": 0}
                ],
                "top_paths_by_lines_added": [
                    {
                        "repo": "api",
                        "path": "src/<script>alert(1)</script>.py",
                        "path_class": "source",
                        "files_changed": 1,
                        "lines_added": 1,
                        "lines_deleted": 0,
                    }
                ],
                "caveats": ["<strong>raw git churn</strong>"],
            }
        ),
        encoding="utf-8",
    )

    publish_static_api(org="chutesai", data_dir=data_dir, site_dir=site_dir)

    dashboard = (site_dir / "chutesai" / "latest" / "dashboard.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in dashboard
    assert '<td class="repo-name">api" onclick="alert(1)</td>' not in dashboard
    assert "api&quot; onclick=&quot;alert(1)" in dashboard
    assert "<strong>raw git churn</strong>" not in dashboard
    assert "run-&lt;unsafe&gt;" in dashboard
    assert "src/&lt;script&gt;alert(1)&lt;/script&gt;.py" in dashboard


def test_publish_static_api_rejects_empty_output_directory(tmp_path):
    from git_crawl.static_api import publish_static_api

    data_dir = tmp_path / "empty"
    data_dir.mkdir()

    with pytest.raises(ValueError, match="no known crawler output files"):
        publish_static_api(org="chutesai", data_dir=data_dir, site_dir=tmp_path / "site")


@pytest.mark.parametrize(
    ("org", "run_label"),
    [
        (".", "latest"),
        ("..", "latest"),
        ("chutesai", "."),
        ("chutesai", ".."),
    ],
)
def test_publish_static_api_rejects_dot_path_segments(tmp_path, org, run_label):
    from git_crawl.static_api import publish_static_api

    data_dir = tmp_path / "crawl-out"
    data_dir.mkdir()
    (data_dir / "summary.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must not be a dot path segment"):
        publish_static_api(org=org, run_label=run_label, data_dir=data_dir, site_dir=tmp_path / "site")
