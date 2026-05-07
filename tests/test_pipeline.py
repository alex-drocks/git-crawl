import sqlite3
import threading
import time
from pathlib import Path

from git_crawl.github import RepoInfo
from git_crawl.pipeline import crawl_org, crawl_owner, crawl_repositories
from git_crawl.state import CrawlStateStore


def _repo_info(owner: str, name: str, *, pushed_at: str = "2026-05-01T00:00:00Z") -> RepoInfo:
    return RepoInfo(
        name=name,
        full_name=f"{owner}/{name}",
        clone_url=f"https://github.com/{owner}/{name}.git",
        ssh_url=f"git@github.com:{owner}/{name}.git",
        default_branch="main",
        pushed_at=pushed_at,
        archived=False,
        fork=False,
        private=False,
        language="Python",
    )


def test_crawl_owner_discovers_org_or_user_repos_and_uses_full_repo_identity(monkeypatch, tmp_path):
    repo = _repo_info("alice", "portfolio", pushed_at="2026-05-02T00:00:00Z")
    captured = {}

    def fake_list_owner_repositories(owner, **kwargs):
        captured["owner"] = owner
        captured["owner_kwargs"] = kwargs
        return [repo]

    monkeypatch.setattr("git_crawl.pipeline.list_owner_repositories", fake_list_owner_repositories)
    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", lambda repo, cache_dir, prefer_ssh=False: tmp_path / repo.full_name)
    monkeypatch.setattr("git_crawl.pipeline.get_ref_sha", lambda mirror, ref: "newsha")
    monkeypatch.setattr(
        "git_crawl.pipeline.read_commit_log",
        lambda mirror, *, since=None, until=None, revision=None, all_refs=False: (
            "\x1enewsha\x1fAlice Example\x1falice@example.com\x1f"
            "2026-05-04T10:15:00+00:00\x1f\n"
            "1\t0\tREADME.md\n"
        ),
    )

    state_db = tmp_path / "state.sqlite"
    result = crawl_owner(
        "alice",
        cache_dir=tmp_path / "mirrors",
        state_db=state_db,
        owner_type="auto",
    )

    assert captured["owner"] == "alice"
    assert captured["owner_kwargs"]["owner_type"] == "auto"
    assert result.org == "alice"
    assert [row.repo for row in result.raw_commits] == ["alice/portfolio"]
    store = CrawlStateStore(state_db)
    assert store.get_repo_state(org="alice", repo="alice/portfolio") is not None
    assert store.get_repo_state(org="alice", repo="portfolio") is None


def test_crawl_repositories_uses_full_names_for_cross_owner_repo_identity(monkeypatch, tmp_path):
    repos = [
        _repo_info("alice", "api", pushed_at="2026-05-02T00:00:00Z"),
        _repo_info("bob", "api", pushed_at="2026-05-01T00:00:00Z"),
    ]

    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", lambda repo, cache_dir, prefer_ssh=False: tmp_path / repo.full_name)
    monkeypatch.setattr("git_crawl.pipeline.get_ref_sha", lambda mirror, ref: "newsha")

    def fake_read_commit_log(mirror, *, since=None, until=None, revision=None, all_refs=False):
        return (
            f"\x1e{str(mirror).split('/')[-2]}-{str(mirror).split('/')[-1]}\x1fAlice Example\x1falice@example.com\x1f"
            "2026-05-04T10:15:00+00:00\x1f\n"
            "1\t0\tsrc/app.py\n"
        )

    monkeypatch.setattr("git_crawl.pipeline.read_commit_log", fake_read_commit_log)

    state_db = tmp_path / "state.sqlite"
    result = crawl_repositories(
        "bittensor-subnets",
        repos,
        cache_dir=tmp_path / "mirrors",
        state_db=state_db,
        ref_scope="default-branch",
    )

    assert [repo.full_name for repo in result.repositories] == ["alice/api", "bob/api"]
    assert [row.repo for row in result.raw_commits] == ["alice/api", "bob/api"]
    store = CrawlStateStore(state_db)
    assert store.get_repo_state(org="bittensor-subnets", repo="alice/api") is not None
    assert store.get_repo_state(org="bittensor-subnets", repo="bob/api") is not None
    assert store.get_repo_state(org="bittensor-subnets", repo="api") is None


def test_crawl_repositories_does_not_advance_state_for_failed_fail_fast_run(monkeypatch, tmp_path):
    repos = [
        _repo_info("chutesai", "api", pushed_at="2026-05-02T00:00:00Z"),
        _repo_info("chutesai", "web", pushed_at="2026-05-01T00:00:00Z"),
    ]

    def fake_ensure_mirror(repo, cache_dir, prefer_ssh=False):
        if repo.name == "web":
            raise RuntimeError("clone failed")
        return tmp_path / f"{repo.name}.git"

    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", fake_ensure_mirror)
    monkeypatch.setattr("git_crawl.pipeline.get_ref_sha", lambda mirror, ref: "api-newsha")
    monkeypatch.setattr(
        "git_crawl.pipeline.read_commit_log",
        lambda mirror, *, since=None, until=None, revision=None, all_refs=False: (
            "\x1eapi-commit\x1fAlice Example\x1falice@example.com\x1f"
            "2026-05-04T10:15:00+00:00\x1f\n"
            "1\t0\tsrc/app.py\n"
        ),
    )

    state_db = tmp_path / "state.sqlite"
    result = crawl_repositories(
        "bittensor-subnets",
        repos,
        cache_dir=tmp_path / "mirrors",
        state_db=state_db,
        fail_fast=True,
    )

    assert result.run.status == "failed"
    assert [failure.repo for failure in result.failed_repositories] == ["chutesai/web"]
    assert CrawlStateStore(state_db).get_repo_state(org="bittensor-subnets", repo="chutesai/api") is None


def test_crawl_org_defaults_to_default_branch_and_updates_sqlite_state(monkeypatch, tmp_path):
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
    seen = {}

    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: [repo])
    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", lambda repo, cache_dir, prefer_ssh=False: Path("/tmp/api.git"))
    monkeypatch.setattr("git_crawl.pipeline.get_ref_sha", lambda mirror, ref: "newsha")

    def fake_read_commit_log(mirror, *, since=None, until=None, revision=None, all_refs=False):
        seen["revision"] = revision
        seen["all_refs"] = all_refs
        return (
            "\x1enewsha\x1fAlice Example\x1falice@example.com\x1f"
            "2026-05-04T10:15:00+00:00\x1f\n"
            "10\t2\tsrc/app.py\n"
        )

    monkeypatch.setattr("git_crawl.pipeline.read_commit_log", fake_read_commit_log)

    state_db = tmp_path / "state.sqlite"
    result = crawl_org(
        "chutesai",
        cache_dir=tmp_path / "mirrors",
        state_db=state_db,
        ref_scope="default-branch",
        workers=2,
    )

    assert seen == {"revision": "refs/heads/main", "all_refs": False}
    assert result.run.status == "success"
    assert result.run.repositories_discovered == 1
    assert result.run.repositories_crawled == 1
    assert result.run.commits_parsed == 1
    assert len(result.raw_commits) == 1
    assert len(result.file_changes) == 1

    repo_state = CrawlStateStore(state_db).get_repo_state(org="chutesai", repo="api")
    assert repo_state is not None
    assert repo_state.last_ref_sha == "newsha"


def test_crawl_org_uses_previous_default_branch_sha_for_incremental_ranges(monkeypatch, tmp_path):
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
    store = CrawlStateStore(tmp_path / "state.sqlite")
    run = store.start_run(org="chutesai", ref_scope="default-branch", history_since=None, history_until=None, active_since=None)
    store.update_repo_state(
        org="chutesai",
        repo="api",
        default_branch="main",
        last_ref_sha="oldsha",
        run_id=run.run_id,
    )
    store.finish_run(
        run.run_id,
        status="success",
        repositories_discovered=1,
        repositories_selected=1,
        repositories_crawled=1,
        repositories_failed=0,
        commits_parsed=1,
        error_message=None,
    )
    seen = {}

    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: [repo])
    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", lambda repo, cache_dir, prefer_ssh=False: Path("/tmp/api.git"))
    monkeypatch.setattr("git_crawl.pipeline.get_ref_sha", lambda mirror, ref: "newsha")
    monkeypatch.setattr("git_crawl.pipeline.commit_exists", lambda mirror, sha: True)

    def fake_read_commit_log(mirror, *, since=None, until=None, revision=None, all_refs=False):
        seen["revision"] = revision
        return ""

    monkeypatch.setattr("git_crawl.pipeline.read_commit_log", fake_read_commit_log)

    crawl_org(
        "chutesai",
        cache_dir=tmp_path / "mirrors",
        state_db=tmp_path / "state.sqlite",
        ref_scope="default-branch",
    )

    assert seen["revision"] == "oldsha..newsha"


def test_crawl_org_marks_run_failed_when_every_selected_repository_fails(monkeypatch, tmp_path):
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

    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: [repo])

    def failing_ensure_mirror(repo, cache_dir, prefer_ssh=False):
        raise RuntimeError("clone failed")

    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", failing_ensure_mirror)

    result = crawl_org(
        "chutesai",
        cache_dir=tmp_path / "mirrors",
        state_db=tmp_path / "state.sqlite",
    )

    assert result.run.status == "failed"
    assert result.run.repositories_selected == 1
    assert result.run.repositories_crawled == 0
    assert result.run.repositories_failed == 1
    assert len(result.failed_repositories) == 1


def test_crawl_org_fail_fast_returns_failed_result_with_failure_row(monkeypatch, tmp_path):
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

    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: [repo])

    def failing_ensure_mirror(repo, cache_dir, prefer_ssh=False):
        raise RuntimeError("clone failed")

    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", failing_ensure_mirror)

    result = crawl_org(
        "chutesai",
        cache_dir=tmp_path / "mirrors",
        state_db=tmp_path / "state.sqlite",
        fail_fast=True,
    )

    assert result.run.status == "failed"
    assert result.run.repositories_failed == 1
    assert len(result.failed_repositories) == 1


def test_crawl_org_fail_fast_runs_sequentially_even_when_workers_requested(monkeypatch, tmp_path):
    repos = [
        RepoInfo(
            name="api",
            full_name="chutesai/api",
            clone_url="https://github.com/chutesai/api.git",
            ssh_url="git@github.com:chutesai/api.git",
            default_branch="main",
            pushed_at="2026-05-02T00:00:00Z",
            archived=False,
            fork=False,
            private=False,
            language="Python",
        ),
        RepoInfo(
            name="web",
            full_name="chutesai/web",
            clone_url="https://github.com/chutesai/web.git",
            ssh_url="git@github.com:chutesai/web.git",
            default_branch="main",
            pushed_at="2026-05-01T00:00:00Z",
            archived=False,
            fork=False,
            private=False,
            language="Python",
        ),
    ]
    active = 0
    max_active = 0
    started = []
    lock = threading.Lock()

    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: repos)

    def failing_ensure_mirror(repo, cache_dir, prefer_ssh=False):
        nonlocal active, max_active
        with lock:
            started.append(repo.name)
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        raise RuntimeError(f"{repo.name} clone failed")

    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", failing_ensure_mirror)

    result = crawl_org(
        "chutesai",
        cache_dir=tmp_path / "mirrors",
        state_db=tmp_path / "state.sqlite",
        workers=2,
        fail_fast=True,
    )

    assert started == ["api"]
    assert max_active == 1
    assert result.run.status == "failed"
    assert result.run.repositories_failed == 1
    assert len(result.failed_repositories) == 1


def test_crawl_org_treats_missing_default_branch_ref_as_empty_success(monkeypatch, tmp_path):
    repo = RepoInfo(
        name="empty",
        full_name="chutesai/empty",
        clone_url="https://github.com/chutesai/empty.git",
        ssh_url="git@github.com:chutesai/empty.git",
        default_branch="main",
        pushed_at="2026-05-01T00:00:00Z",
        archived=False,
        fork=False,
        private=False,
        language=None,
    )

    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: [repo])
    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", lambda repo, cache_dir, prefer_ssh=False: Path("/tmp/empty.git"))
    monkeypatch.setattr("git_crawl.pipeline.get_ref_sha", lambda mirror, ref: None)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("missing default branch should not call git log")

    monkeypatch.setattr("git_crawl.pipeline.read_commit_log", fail_if_called)

    result = crawl_org("chutesai", cache_dir=tmp_path / "mirrors", state_db=tmp_path / "state.sqlite")

    assert result.run.status == "success"
    assert result.run.repositories_crawled == 1
    assert result.run.commits_parsed == 0
    assert result.failed_repositories == []


def test_crawl_org_ignores_incremental_state_when_default_branch_changes(monkeypatch, tmp_path):
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
    store = CrawlStateStore(tmp_path / "state.sqlite")
    run = store.start_run(org="chutesai", ref_scope="default-branch", history_since=None, history_until=None, active_since=None)
    store.update_repo_state(
        org="chutesai",
        repo="api",
        default_branch="master",
        last_ref_sha="oldsha",
        run_id=run.run_id,
        history_since=None,
        history_until=None,
    )
    store.finish_run(
        run.run_id,
        status="success",
        repositories_discovered=1,
        repositories_selected=1,
        repositories_crawled=1,
        repositories_failed=0,
        commits_parsed=1,
        error_message=None,
    )
    seen = {}

    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: [repo])
    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", lambda repo, cache_dir, prefer_ssh=False: Path("/tmp/api.git"))
    monkeypatch.setattr("git_crawl.pipeline.get_ref_sha", lambda mirror, ref: "newsha")
    monkeypatch.setattr("git_crawl.pipeline.commit_exists", lambda mirror, sha: True)

    def fake_read_commit_log(mirror, *, since=None, until=None, revision=None, all_refs=False):
        seen["revision"] = revision
        return ""

    monkeypatch.setattr("git_crawl.pipeline.read_commit_log", fake_read_commit_log)

    crawl_org("chutesai", cache_dir=tmp_path / "mirrors", state_db=tmp_path / "state.sqlite")

    assert seen["revision"] == "refs/heads/main"


def test_crawl_org_falls_back_to_full_default_branch_when_previous_sha_is_missing(monkeypatch, tmp_path):
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
    store = CrawlStateStore(tmp_path / "state.sqlite")
    run = store.start_run(org="chutesai", ref_scope="default-branch", history_since="2026-01-01", history_until=None, active_since=None)
    store.update_repo_state(
        org="chutesai",
        repo="api",
        default_branch="main",
        last_ref_sha="oldsha",
        run_id=run.run_id,
        history_since="2026-01-01",
        history_until=None,
    )
    store.finish_run(
        run.run_id,
        status="success",
        repositories_discovered=1,
        repositories_selected=1,
        repositories_crawled=1,
        repositories_failed=0,
        commits_parsed=1,
        error_message=None,
    )
    seen = {}

    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: [repo])
    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", lambda repo, cache_dir, prefer_ssh=False: Path("/tmp/api.git"))
    monkeypatch.setattr("git_crawl.pipeline.get_ref_sha", lambda mirror, ref: "newsha")
    monkeypatch.setattr("git_crawl.pipeline.commit_exists", lambda mirror, sha: False)

    def fake_read_commit_log(mirror, *, since=None, until=None, revision=None, all_refs=False):
        seen["revision"] = revision
        return ""

    monkeypatch.setattr("git_crawl.pipeline.read_commit_log", fake_read_commit_log)

    crawl_org("chutesai", cache_dir=tmp_path / "mirrors", state_db=tmp_path / "state.sqlite", since="2026-01-01")

    assert seen["revision"] == "refs/heads/main"


def test_crawl_org_ignores_legacy_repo_state_with_unknown_history_window(monkeypatch, tmp_path):
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
    with sqlite3.connect(state_db) as connection:
        connection.execute(
            """
            create table repo_states (
                org text not null,
                repo text not null,
                default_branch text not null,
                last_ref_sha text not null,
                last_successful_run_id text not null,
                last_crawled_at text not null,
                primary key (org, repo)
            )
            """
        )
        connection.execute(
            """
            insert into repo_states (
                org, repo, default_branch, last_ref_sha,
                last_successful_run_id, last_crawled_at
            ) values (?, ?, ?, ?, ?, ?)
            """,
            ("chutesai", "api", "main", "oldsha", "legacy-run", "2026-05-01T00:00:00+00:00"),
        )

    seen = {}
    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: [repo])
    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", lambda repo, cache_dir, prefer_ssh=False: Path("/tmp/api.git"))
    monkeypatch.setattr("git_crawl.pipeline.get_ref_sha", lambda mirror, ref: "oldsha")

    def fake_read_commit_log(mirror, *, since=None, until=None, revision=None, all_refs=False):
        seen["revision"] = revision
        return ""

    monkeypatch.setattr("git_crawl.pipeline.read_commit_log", fake_read_commit_log)

    crawl_org("chutesai", cache_dir=tmp_path / "mirrors", state_db=state_db)

    assert seen["revision"] == "refs/heads/main"



def test_crawl_org_ignores_legacy_repo_state_without_semantics_provenance(monkeypatch, tmp_path):
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
    with sqlite3.connect(state_db) as connection:
        connection.execute(
            """
            create table repo_states (
                org text not null,
                repo text not null,
                default_branch text not null,
                last_ref_sha text not null,
                history_since text,
                history_until text,
                last_successful_run_id text not null,
                last_crawled_at text not null,
                primary key (org, repo)
            )
            """
        )
        connection.execute(
            """
            insert into repo_states (
                org, repo, default_branch, last_ref_sha, history_since, history_until,
                last_successful_run_id, last_crawled_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "chutesai",
                "api",
                "main",
                "headsha",
                "2026-01-01",
                None,
                "legacy-run",
                "2026-05-01T00:00:00+00:00",
            ),
        )

    seen = {}
    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: [repo])
    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", lambda repo, cache_dir, prefer_ssh=False: Path("/tmp/api.git"))
    monkeypatch.setattr("git_crawl.pipeline.get_ref_sha", lambda mirror, ref: "headsha")

    def fake_read_commit_log(mirror, *, since=None, until=None, revision=None, all_refs=False):
        seen["revision"] = revision
        return ""

    monkeypatch.setattr("git_crawl.pipeline.read_commit_log", fake_read_commit_log)

    crawl_org("chutesai", cache_dir=tmp_path / "mirrors", state_db=state_db, since="2026-01-01")

    assert seen["revision"] == "refs/heads/main"



def test_crawl_org_crawls_multiple_repos_and_orders_parallel_outputs_deterministically(monkeypatch, tmp_path):
    repos = [
        RepoInfo(
            name="api",
            full_name="chutesai/api",
            clone_url="https://github.com/chutesai/api.git",
            ssh_url="git@github.com:chutesai/api.git",
            default_branch="main",
            pushed_at="2026-05-02T00:00:00Z",
            archived=False,
            fork=False,
            private=False,
            language="Python",
        ),
        RepoInfo(
            name="web",
            full_name="chutesai/web",
            clone_url="https://github.com/chutesai/web.git",
            ssh_url="git@github.com:chutesai/web.git",
            default_branch="main",
            pushed_at="2026-05-01T00:00:00Z",
            archived=False,
            fork=False,
            private=False,
            language="TypeScript",
        ),
    ]
    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: repos)

    def fake_ensure_mirror(repo, cache_dir, prefer_ssh=False):
        if repo.name == "api":
            time.sleep(0.05)
        return Path(f"/tmp/{repo.name}.git")

    def fake_get_ref_sha(mirror, ref):
        return f"{Path(mirror).stem}-head"

    def fake_read_commit_log(mirror, *, since=None, until=None, revision=None, all_refs=False):
        repo_name = Path(mirror).stem
        return (
            f"\x1e{repo_name}-sha\x1fAlice Example\x1falice@example.com\x1f"
            "2026-05-04T10:15:00+00:00\x1f\n"
            f"{10 if repo_name == 'api' else 20}\t1\tsrc/{repo_name}.py\n"
        )

    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", fake_ensure_mirror)
    monkeypatch.setattr("git_crawl.pipeline.get_ref_sha", fake_get_ref_sha)
    monkeypatch.setattr("git_crawl.pipeline.read_commit_log", fake_read_commit_log)

    result = crawl_org("chutesai", cache_dir=tmp_path / "mirrors", workers=2)

    assert result.run.status == "success"
    assert result.run.repositories_discovered == 2
    assert result.run.repositories_crawled == 2
    assert [row.repo for row in result.raw_commits] == ["api", "web"]
    assert [row.repo for row in result.file_changes] == ["api", "web"]
    assert [(row.repo, row.commits) for row in result.aggregates.repo_days] == [("api", 1), ("web", 1)]
    assert len(result.aggregates.org_days) == 1
    org_day = result.aggregates.org_days[0]
    assert org_day.commits == 2
    assert org_day.unique_contributors == 1
    assert org_day.lines_added == 30
    assert org_day.lines_deleted == 2
    assert org_day.files_changed == 2


def test_crawl_org_ignores_incremental_state_when_history_window_changes(monkeypatch, tmp_path):
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
    store = CrawlStateStore(tmp_path / "state.sqlite")
    run = store.start_run(org="chutesai", ref_scope="default-branch", history_since="2026-01-01", history_until=None, active_since=None)
    store.update_repo_state(
        org="chutesai",
        repo="api",
        default_branch="main",
        last_ref_sha="oldsha",
        run_id=run.run_id,
        history_since="2026-01-01",
        history_until=None,
    )
    store.finish_run(
        run.run_id,
        status="success",
        repositories_discovered=1,
        repositories_selected=1,
        repositories_crawled=1,
        repositories_failed=0,
        commits_parsed=1,
        error_message=None,
    )
    seen = {}

    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: [repo])
    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", lambda repo, cache_dir, prefer_ssh=False: Path("/tmp/api.git"))
    monkeypatch.setattr("git_crawl.pipeline.get_ref_sha", lambda mirror, ref: "oldsha")

    def fake_read_commit_log(mirror, *, since=None, until=None, revision=None, all_refs=False):
        seen["revision"] = revision
        return ""

    monkeypatch.setattr("git_crawl.pipeline.read_commit_log", fake_read_commit_log)

    crawl_org("chutesai", cache_dir=tmp_path / "mirrors", state_db=tmp_path / "state.sqlite", since="2025-01-01")

    assert seen["revision"] == "refs/heads/main"


def test_crawl_org_filters_history_window_by_author_timestamp_after_git_log(monkeypatch, tmp_path):
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

    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: [repo])
    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", lambda repo, cache_dir, prefer_ssh=False: Path("/tmp/api.git"))
    monkeypatch.setattr("git_crawl.pipeline.get_ref_sha", lambda mirror, ref: "newsha")

    def fake_read_commit_log(mirror, *, since=None, until=None, revision=None, all_refs=False):
        assert since is None
        assert until is None
        assert revision == "refs/heads/main"
        return (
            "\x1eold\x1fAlice Example\x1falice@example.com\x1f"
            "2020-01-01T10:15:00+00:00\x1f\n"
            "1\t0\told.py\n"
            "\x1enew\x1fAlice Example\x1falice@example.com\x1f"
            "2026-05-04T10:15:00+00:00\x1f\n"
            "2\t0\tnew.py\n"
        )

    monkeypatch.setattr("git_crawl.pipeline.read_commit_log", fake_read_commit_log)

    result = crawl_org("chutesai", cache_dir=tmp_path / "mirrors", state_db=tmp_path / "state.sqlite", since="2026-01-01")

    assert [row.sha for row in result.raw_commits] == ["new"]
    assert [row.date for row in result.aggregates.org_days] == ["2026-05-04"]


def test_crawl_org_redacts_credentials_from_repo_failures_and_run_errors(monkeypatch, tmp_path):
    credentialed_url = "https://sensitive-userinfo@github.com/chutesai/api.git"
    repo = RepoInfo(
        name="api",
        full_name="chutesai/api",
        clone_url=credentialed_url,
        ssh_url="git@github.com:chutesai/api.git",
        default_branch="main",
        pushed_at="2026-05-01T00:00:00Z",
        archived=False,
        fork=False,
        private=False,
        language="Python",
    )

    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: [repo])

    def failing_ensure_mirror(repo, cache_dir, prefer_ssh=False):
        raise RuntimeError(f"clone failed for {repo.clone_url}")

    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", failing_ensure_mirror)

    result = crawl_org("chutesai", cache_dir=tmp_path / "mirrors", state_db=tmp_path / "state.sqlite")

    assert result.failed_repositories
    assert "sensitive-userinfo" not in result.failed_repositories[0].error
    assert result.run.error_message is not None
    assert "sensitive-userinfo" not in result.run.error_message
    assert "[REDACTED]" in result.failed_repositories[0].error


def test_crawl_org_records_excluded_repositories_with_reasons(monkeypatch, tmp_path):
    repos = [
        RepoInfo(
            name="source",
            full_name="chutesai/source",
            clone_url="https://github.com/chutesai/source.git",
            ssh_url="git@github.com:chutesai/source.git",
            default_branch="main",
            pushed_at="2026-05-04T00:00:00Z",
            archived=False,
            fork=False,
            private=False,
            language="Python",
        ),
        RepoInfo(
            name="forked",
            full_name="chutesai/forked",
            clone_url="https://github.com/chutesai/forked.git",
            ssh_url="git@github.com:chutesai/forked.git",
            default_branch="main",
            pushed_at="2026-05-03T00:00:00Z",
            archived=False,
            fork=True,
            private=False,
            language="Python",
        ),
        RepoInfo(
            name="archived",
            full_name="chutesai/archived",
            clone_url="https://github.com/chutesai/archived.git",
            ssh_url="git@github.com:chutesai/archived.git",
            default_branch="main",
            pushed_at="2026-05-02T00:00:00Z",
            archived=True,
            fork=False,
            private=False,
            language="Python",
        ),
        RepoInfo(
            name="old",
            full_name="chutesai/old",
            clone_url="https://github.com/chutesai/old.git",
            ssh_url="git@github.com:chutesai/old.git",
            default_branch="main",
            pushed_at="2020-01-01T00:00:00Z",
            archived=False,
            fork=False,
            private=False,
            language="Python",
        ),
    ]
    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: repos)
    monkeypatch.setattr("git_crawl.pipeline.ensure_mirror", lambda repo, cache_dir, prefer_ssh=False: Path(f"/tmp/{repo.name}.git"))
    monkeypatch.setattr("git_crawl.pipeline.get_ref_sha", lambda mirror, ref: None)

    result = crawl_org(
        "chutesai",
        cache_dir=tmp_path / "mirrors",
        state_db=tmp_path / "state.sqlite",
        active_since="2026-01-01T00:00:00Z",
    )

    assert [repo.name for repo in result.repositories] == ["source"]
    assert [(row.name, row.exclusion_reason) for row in result.excluded_repositories] == [
        ("forked", "fork"),
        ("archived", "archived"),
        ("old", "inactive_before_active_since"),
    ]
