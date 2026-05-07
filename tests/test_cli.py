import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from git_crawl.cli import main
from git_crawl.github import RepoInfo
from git_crawl.state import CrawlStateStore


def test_cli_crawl_owner_delegates_to_owner_crawler(monkeypatch, tmp_path, capsys):
    repo = RepoInfo(
        name="portfolio",
        full_name="alice/portfolio",
        clone_url="https://github.com/alice/portfolio.git",
        ssh_url="git@github.com:alice/portfolio.git",
        default_branch="main",
        pushed_at="2026-05-01T00:00:00Z",
        archived=False,
        fork=False,
        private=False,
        language="Python",
    )
    captured = {}

    def fake_crawl_owner(owner, **kwargs):
        captured["owner"] = owner
        captured["crawl_kwargs"] = kwargs
        return SimpleNamespace(
            org=kwargs.get("target") or owner,
            run=SimpleNamespace(run_id="run-owner", status="success"),
            repositories=[repo],
            commits=[],
            file_changes=[],
            aggregates=SimpleNamespace(repo_days=[], contributor_days=[], org_days=[]),
            failed_repositories=[],
        )

    monkeypatch.setattr("git_crawl.cli.crawl_owner", fake_crawl_owner)
    monkeypatch.setattr("git_crawl.cli.finalize_crawl_state", lambda result, state_db, **kwargs: result)
    monkeypatch.setattr("git_crawl.cli.write_crawl_outputs", lambda *args, **kwargs: [tmp_path / "out" / "summary.json"])

    exit_code = main(
        [
            "crawl-owner",
            "alice",
            "--owner-type",
            "user",
            "--target",
            "bittensor-subnet-64",
            "--output-dir",
            str(tmp_path / "out"),
            "--cache-dir",
            str(tmp_path / "mirrors"),
            "--state-db",
            str(tmp_path / "state.sqlite"),
            "--workers",
            "2",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert captured["owner"] == "alice"
    assert captured["crawl_kwargs"]["target"] == "bittensor-subnet-64"
    assert captured["crawl_kwargs"]["owner_type"] == "user"
    assert captured["crawl_kwargs"]["workers"] == 2
    assert captured["crawl_kwargs"]["state_db"] == str(tmp_path / "state.sqlite")
    assert "Crawled 1 repos for target bittensor-subnet-64 from owner alice" in output
    assert str(tmp_path / "out" / "summary.json") in output


def test_cli_crawl_repos_loads_manifest_and_delegates_to_explicit_repo_crawler(monkeypatch, tmp_path, capsys):
    manifest_path = tmp_path / "repos.json"
    manifest_path.write_text(
        json.dumps(
            {
                "target": "bittensor-subnets",
                "repositories": [
                    "https://github.com/alice/api",
                    {"url": "https://github.com/bob/api/tree/main"},
                ],
            }
        ),
        encoding="utf-8",
    )
    repo = RepoInfo(
        name="api",
        full_name="alice/api",
        clone_url="https://github.com/alice/api.git",
        ssh_url="git@github.com:alice/api.git",
        default_branch="main",
        pushed_at="2026-05-01T00:00:00Z",
        archived=False,
        fork=False,
        private=False,
        language="Python",
    )
    captured = {}

    def fake_list_repositories_from_urls(urls, **kwargs):
        captured["urls"] = list(urls)
        captured["resolve_kwargs"] = kwargs
        return [repo]

    def fake_crawl_repositories(target, repositories, **kwargs):
        captured["target"] = target
        captured["repositories"] = repositories
        captured["crawl_kwargs"] = kwargs
        return SimpleNamespace(
            org=target,
            run=SimpleNamespace(run_id="run-1", status="success"),
            repositories=repositories,
            commits=[],
            file_changes=[],
            aggregates=SimpleNamespace(repo_days=[], contributor_days=[], org_days=[]),
            failed_repositories=[],
        )

    monkeypatch.setattr("git_crawl.cli.list_repositories_from_urls", fake_list_repositories_from_urls)
    monkeypatch.setattr("git_crawl.cli.crawl_repositories", fake_crawl_repositories)
    monkeypatch.setattr("git_crawl.cli.finalize_crawl_state", lambda result, state_db, **kwargs: result)
    monkeypatch.setattr("git_crawl.cli.write_crawl_outputs", lambda *args, **kwargs: [tmp_path / "out" / "summary.json"])

    exit_code = main(
        [
            "crawl-repos",
            str(manifest_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--cache-dir",
            str(tmp_path / "mirrors"),
            "--state-db",
            str(tmp_path / "state.sqlite"),
            "--workers",
            "2",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert captured["urls"] == ["https://github.com/alice/api", "https://github.com/bob/api/tree/main"]
    assert captured["target"] == "bittensor-subnets"
    assert captured["repositories"] == [repo]
    assert captured["crawl_kwargs"]["workers"] == 2
    assert captured["crawl_kwargs"]["state_db"] == str(tmp_path / "state.sqlite")
    assert "Crawled 1 repos for bittensor-subnets" in output
    assert str(tmp_path / "out" / "summary.json") in output


def test_cli_crawl_repos_passes_max_repos_to_manifest_resolution(monkeypatch, tmp_path, capsys):
    manifest_path = tmp_path / "repos.json"
    manifest_path.write_text(
        json.dumps(
            {
                "target": "bittensor-subnets",
                "repositories": [
                    "https://github.com/alice/api",
                    "https://github.com/bob/web",
                    "https://github.com/dead/missing",
                ],
            }
        ),
        encoding="utf-8",
    )
    repos = [
        RepoInfo(
            name="api",
            full_name="alice/api",
            clone_url="https://github.com/alice/api.git",
            ssh_url="git@github.com:alice/api.git",
            default_branch="main",
            pushed_at="2026-05-01T00:00:00Z",
            archived=False,
            fork=False,
            private=False,
            language="Python",
        ),
        RepoInfo(
            name="web",
            full_name="bob/web",
            clone_url="https://github.com/bob/web.git",
            ssh_url="git@github.com:bob/web.git",
            default_branch="main",
            pushed_at="2026-05-01T00:00:00Z",
            archived=False,
            fork=False,
            private=False,
            language="TypeScript",
        ),
    ]
    captured = {}

    def fake_list_repositories_from_urls(urls, **kwargs):
        captured["urls"] = list(urls)
        captured["resolve_kwargs"] = kwargs
        return repos

    def fake_crawl_repositories(target, repositories, **kwargs):
        captured["crawl_kwargs"] = kwargs
        return SimpleNamespace(
            org=target,
            run=SimpleNamespace(run_id="run-1", status="success"),
            repositories=repositories,
            commits=[],
            file_changes=[],
            aggregates=SimpleNamespace(repo_days=[], contributor_days=[], org_days=[]),
            failed_repositories=[],
        )

    monkeypatch.setattr("git_crawl.cli.list_repositories_from_urls", fake_list_repositories_from_urls)
    monkeypatch.setattr("git_crawl.cli.crawl_repositories", fake_crawl_repositories)
    monkeypatch.setattr("git_crawl.cli.write_crawl_outputs", lambda *args, **kwargs: [tmp_path / "out" / "summary.json"])

    exit_code = main(["crawl-repos", str(manifest_path), "--max-repos", "2"])

    assert exit_code == 0
    assert captured["urls"] == [
        "https://github.com/alice/api",
        "https://github.com/bob/web",
        "https://github.com/dead/missing",
    ]
    assert captured["resolve_kwargs"]["max_repos"] == 2
    assert captured["crawl_kwargs"]["max_repos"] == 2
    assert "Crawled 2 repos for bittensor-subnets" in capsys.readouterr().out


def test_cli_crawl_repos_reports_sanitized_repository_resolution_errors(tmp_path, capsys):
    manifest = tmp_path / "repos.json"
    manifest.write_text(
        json.dumps(
            {
                "target": "bittensor-subnets",
                "repositories": ["https://x-access-token:SECRET123@github.com/chutesai/api/issues/1"],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["crawl-repos", str(manifest)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "failed to resolve repositories" in captured.err
    assert "SECRET123" not in captured.err
    assert "x-access-token" not in captured.err


def test_cli_boolean_flags_can_override_true_config_values(monkeypatch, tmp_path):
    config_path = tmp_path / "crawler.toml"
    config_path.write_text(
        """
org = "chutesai"

[filters]
include_archived = true
include_forks = true
""".strip(),
        encoding="utf-8",
    )
    captured = {}

    def fake_crawl_org(org, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            org=org,
            run=SimpleNamespace(run_id="run-1", status="success"),
            repositories=[],
            commits=[],
            file_changes=[],
            aggregates=SimpleNamespace(repo_days=[], contributor_days=[], org_days=[]),
            failed_repositories=[],
        )

    monkeypatch.setattr("git_crawl.cli.crawl_org", fake_crawl_org)
    monkeypatch.setattr("git_crawl.cli.write_crawl_outputs", lambda *args, **kwargs: [])

    assert main(["crawl-org", "--config", str(config_path), "--no-include-archived", "--no-include-forks"]) == 0

    assert captured["include_archived"] is False
    assert captured["include_forks"] is False


def test_cli_does_not_advance_sqlite_state_when_output_write_fails(monkeypatch, tmp_path, capsys):
    repo = RepoInfo(
        name="api",
        full_name="chutesai/api",
        clone_url="https://github.com/chutesai/api.git",
        ssh_url="git@github.com:chutesai/api.git",
        default_branch="main",
        pushed_at="2026-05-01T00:00:00Z",
        archived=False,
        fork=False,
        private=False,
        language="Python",
    )
    state_db = tmp_path / "state.sqlite"
    store = CrawlStateStore(state_db)
    prior_run = store.start_run(
        org="chutesai",
        ref_scope="default-branch",
        history_since=None,
        history_until=None,
        active_since=None,
    )
    store.update_repo_state(
        org="chutesai",
        repo="api",
        default_branch="main",
        last_ref_sha="oldsha",
        run_id=prior_run.run_id,
    )
    store.finish_run(
        prior_run.run_id,
        status="success",
        repositories_discovered=1,
        repositories_selected=1,
        repositories_crawled=1,
        repositories_failed=0,
        commits_parsed=1,
        error_message=None,
    )

    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: [repo])
    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", lambda repo, cache_dir, prefer_ssh=False: Path("/tmp/api.git"))
    monkeypatch.setattr("git_crawl.pipeline.get_ref_sha", lambda mirror, ref: "newsha")
    monkeypatch.setattr("git_crawl.pipeline.commit_exists", lambda mirror, sha: True)

    def fake_read_commit_log(mirror, *, since=None, until=None, revision=None, all_refs=False):
        assert revision == "oldsha..newsha"
        return (
            "\x1enewsha\x1fAlice Example\x1falice@example.com\x1f"
            "2026-05-04T10:15:00+00:00\x1foldsha\n"
            "1\t0\tsrc/app.py\n"
        )

    def fail_to_write_outputs(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("git_crawl.pipeline.read_commit_log", fake_read_commit_log)
    monkeypatch.setattr("git_crawl.cli.write_crawl_outputs", fail_to_write_outputs)

    exit_code = main(
        [
            "crawl-org",
            "chutesai",
            "--state-db",
            str(state_db),
            "--cache-dir",
            str(tmp_path / "mirrors"),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "failed to write crawl outputs" in captured.err
    assert CrawlStateStore(state_db).get_repo_state(org="chutesai", repo="api").last_ref_sha == "oldsha"

    with sqlite3.connect(state_db) as connection:
        latest_status, latest_error = connection.execute(
            "select status, error_message from crawl_runs order by rowid desc limit 1"
        ).fetchone()
    assert latest_status == "failed"
    assert "output write failed" in latest_error


def test_cli_rejects_non_positive_integer_options_before_crawling():
    with pytest.raises(SystemExit) as workers_exit:
        main(["crawl-org", "chutesai", "--workers", "0"])
    assert workers_exit.value.code == 2

    with pytest.raises(SystemExit) as max_repos_exit:
        main(["crawl-org", "chutesai", "--max-repos", "0"])
    assert max_repos_exit.value.code == 2


def test_cli_build_static_api_delegates_to_publisher(monkeypatch, tmp_path, capsys):
    data_dir = tmp_path / "crawl-out"
    site_dir = tmp_path / "site"
    copied_file = site_dir / "chutesai" / "latest" / "summary.json"
    manifest_file = site_dir / "api" / "chutesai" / "latest.json"
    dashboard_file = site_dir / "chutesai" / "latest" / "dashboard.html"
    captured = {}

    def fake_publish_static_api(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            dataset_dir=site_dir / "chutesai" / "latest",
            copied_files=[copied_file],
            manifest_files=[manifest_file],
            dashboard_files=[dashboard_file],
        )

    monkeypatch.setattr("git_crawl.cli.publish_static_api", fake_publish_static_api, raising=False)

    exit_code = main(
        [
            "build-static-api",
            "chutesai",
            "--data-dir",
            str(data_dir),
            "--site-dir",
            str(site_dir),
            "--run-label",
            "latest",
            "--base-url",
            "https://alex-drocks.github.io/git-crawl",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert captured == {
        "org": "chutesai",
        "data_dir": data_dir,
        "site_dir": site_dir,
        "run_label": "latest",
        "base_url": "https://alex-drocks.github.io/git-crawl",
    }
    assert "Published static API for chutesai at" in output
    assert str(copied_file) in output
    assert str(manifest_file) in output
    assert str(dashboard_file) in output
