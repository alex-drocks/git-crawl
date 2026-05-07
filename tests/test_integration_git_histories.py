from __future__ import annotations

import csv
import json
from pathlib import Path

from git_crawl.cli import main
from git_crawl.github import RepoInfo
from git_crawl.pipeline import (
    COMMIT_FIELDS,
    CONTRIBUTOR_DAY_FIELDS,
    CRAWL_RUN_FIELDS,
    FILE_CHANGE_FIELDS,
    ORG_DAY_FIELDS,
    REPOSITORY_FIELDS,
    REPO_DAY_FIELDS,
    REPO_FAILURE_FIELDS,
    crawl_org,
)
from git_crawl.state import CrawlStateStore


OUTPUT_SCHEMAS = {
    "crawl_runs": CRAWL_RUN_FIELDS,
    "repositories": REPOSITORY_FIELDS,
    "commits": COMMIT_FIELDS,
    "file_changes": FILE_CHANGE_FIELDS,
    "org_days": ORG_DAY_FIELDS,
    "repo_days": REPO_DAY_FIELDS,
    "contributor_days": CONTRIBUTOR_DAY_FIELDS,
    "repo_failures": REPO_FAILURE_FIELDS,
}


def _repo_info(source: Path, *, default_branch: str = "main") -> RepoInfo:
    return RepoInfo(
        name="demo",
        full_name="localorg/demo",
        clone_url=str(source),
        ssh_url=str(source),
        default_branch=default_branch,
        pushed_at="2026-01-10T00:00:00Z",
        archived=False,
        fork=False,
        private=False,
        language="Python",
    )


def _jsonl_rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_crawl_org_reads_real_git_history_with_merges_binary_renames_deletions_and_empty_commits(
    monkeypatch,
    tmp_path,
    local_git_repo,
):
    local_git_repo.write_text("src/app.py", "print('hello')\n")
    local_git_repo.commit("initial app")

    local_git_repo.checkout("feature", create=True)
    local_git_repo.write_text("src/feature.py", "FEATURE_ENABLED = True\n")
    local_git_repo.commit("add feature branch file")

    local_git_repo.checkout("main")
    local_git_repo.write_text("README.md", "# Demo\n")
    local_git_repo.commit("update readme on main")
    merge_sha = local_git_repo.merge_no_ff("feature", "merge feature branch")

    local_git_repo.write_bytes("assets/blob.bin", b"\x00\xff\xfe\xfdgit-crawl-binary\x00")
    binary_sha = local_git_repo.commit("add binary fixture")

    local_git_repo.rename("src/app.py", "src/main.py")
    rename_sha = local_git_repo.commit("rename application module")

    local_git_repo.delete("src/main.py")
    delete_sha = local_git_repo.commit("delete application module")

    empty_sha = local_git_repo.commit("record empty release marker", allow_empty=True)

    monkeypatch.setattr(
        "git_crawl.pipeline.list_org_repositories",
        lambda org, token=None: [_repo_info(local_git_repo.path)],
    )

    result = crawl_org("localorg", cache_dir=tmp_path / "mirrors", state_db=tmp_path / "state.sqlite")

    assert result.run.status == "success"
    assert result.run.repositories_crawled == 1
    assert result.run.commits_parsed == 8

    commits_by_sha = {row.sha: row for row in result.raw_commits}
    assert commits_by_sha[merge_sha].is_merge_commit is True
    assert commits_by_sha[merge_sha].parent_count == 2

    assert commits_by_sha[binary_sha].files_changed == 1
    assert commits_by_sha[binary_sha].lines_added == 0
    assert commits_by_sha[binary_sha].lines_deleted == 0
    binary_change = next(row for row in result.file_changes if row.sha == binary_sha)
    assert binary_change.path == "assets/blob.bin"
    assert binary_change.is_binary is True
    assert binary_change.additions == 0
    assert binary_change.deletions == 0

    rename_change = next(row for row in result.file_changes if row.sha == rename_sha)
    assert rename_change.path == "src/{app.py => main.py}"
    assert rename_change.is_binary is False

    delete_change = next(row for row in result.file_changes if row.sha == delete_sha)
    assert delete_change.path == "src/main.py"
    assert delete_change.additions == 0
    assert delete_change.deletions == 1

    assert commits_by_sha[empty_sha].files_changed == 0
    assert commits_by_sha[empty_sha].lines_added == 0
    assert commits_by_sha[empty_sha].lines_deleted == 0
    assert [row for row in result.file_changes if row.sha == empty_sha] == []


def test_crawl_org_uses_real_mirror_for_incremental_two_run_and_default_branch_changes(
    monkeypatch,
    tmp_path,
    local_git_repo,
):
    local_git_repo.write_text("src/app.py", "one\n")
    first_sha = local_git_repo.commit("initial app")

    discovered = [_repo_info(local_git_repo.path)]
    monkeypatch.setattr("git_crawl.pipeline.list_org_repositories", lambda org, token=None: discovered)

    state_db = tmp_path / "state.sqlite"
    cache_dir = tmp_path / "mirrors"

    first_result = crawl_org("localorg", cache_dir=cache_dir, state_db=state_db)
    assert first_result.run.status == "success"
    assert [commit.sha for commit in first_result.commits] == [first_sha]
    assert CrawlStateStore(state_db).get_repo_state(org="localorg", repo="demo").last_ref_sha == first_sha

    local_git_repo.write_text("src/app.py", "one\ntwo\n")
    second_sha = local_git_repo.commit("append second line")

    second_result = crawl_org("localorg", cache_dir=cache_dir, state_db=state_db)
    assert second_result.run.status == "success"
    assert [commit.sha for commit in second_result.commits] == [second_sha]
    assert second_result.raw_commits[0].lines_added == 1
    assert CrawlStateStore(state_db).get_repo_state(org="localorg", repo="demo").last_ref_sha == second_sha

    local_git_repo.checkout("stable", create=True)
    local_git_repo.write_text("stable.txt", "stable default branch\n")
    stable_sha = local_git_repo.commit("add stable branch marker")
    discovered[:] = [_repo_info(local_git_repo.path, default_branch="stable")]

    branch_change_result = crawl_org("localorg", cache_dir=cache_dir, state_db=state_db)
    assert branch_change_result.run.status == "success"
    assert {commit.sha for commit in branch_change_result.commits} == {first_sha, second_sha, stable_sha}

    repo_state = CrawlStateStore(state_db).get_repo_state(org="localorg", repo="demo")
    assert repo_state.default_branch == "stable"
    assert repo_state.last_ref_sha == stable_sha


def test_cli_end_to_end_writes_outputs_and_validates_schemas(monkeypatch, tmp_path, capsys, local_git_repo):
    local_git_repo.write_text("src/app.py", "print('hello')\n")
    local_git_repo.commit("initial app")
    local_git_repo.write_text("src/app.py", "print('hello')\nprint('world')\n")
    local_git_repo.commit("extend app")

    monkeypatch.setattr(
        "git_crawl.pipeline.list_org_repositories",
        lambda org, token=None: [_repo_info(local_git_repo.path)],
    )

    output_dir = tmp_path / "out"
    exit_code = main(
        [
            "crawl-org",
            "localorg",
            "--cache-dir",
            str(tmp_path / "mirrors"),
            "--state-db",
            str(tmp_path / "state.sqlite"),
            "--output-dir",
            str(output_dir),
            "--format",
            "all",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Crawled 1 repos from localorg: 2 commits" in captured.out

    for stem, fields in OUTPUT_SCHEMAS.items():
        jsonl_path = output_dir / f"{stem}.jsonl"
        csv_path = output_dir / f"{stem}.csv"
        assert jsonl_path.exists()
        assert csv_path.exists()

        with csv_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            assert reader.fieldnames == fields

        json_rows = _jsonl_rows(jsonl_path)
        if json_rows:
            assert set(json_rows[0]) == set(fields)

    crawl_run = _jsonl_rows(output_dir / "crawl_runs.jsonl")[0]
    assert crawl_run["status"] == "success"
    assert crawl_run["repositories_crawled"] == 1
    assert crawl_run["commits_parsed"] == 2

    assert len(_jsonl_rows(output_dir / "repositories.jsonl")) == 1
    assert len(_jsonl_rows(output_dir / "commits.jsonl")) == 2
    assert len(_jsonl_rows(output_dir / "file_changes.jsonl")) == 2
    assert _jsonl_rows(output_dir / "repo_failures.jsonl") == []


def test_crawl_org_preserves_raw_mailmapped_author_and_non_ascii_paths(monkeypatch, tmp_path, local_git_repo):
    local_git_repo.write_text(
        ".mailmap",
        "Canonical Author <canonical@example.com> Original Author <original@example.com>\n",
    )
    local_git_repo.commit("add mailmap")

    local_git_repo.write_text("café.txt", "bonjour\n")
    local_git_repo.run("add", "-A")
    local_git_repo.run(
        "commit",
        "-m",
        "add non ascii path with original author",
        env={
            "GIT_AUTHOR_DATE": "2026-01-01T13:00:00+00:00",
            "GIT_COMMITTER_DATE": "2026-01-01T13:00:00+00:00",
            "GIT_AUTHOR_NAME": "Original Author",
            "GIT_AUTHOR_EMAIL": "original@example.com",
            "GIT_COMMITTER_NAME": "Integration Tester",
            "GIT_COMMITTER_EMAIL": "tester@example.com",
        },
    )
    raw_author_sha = local_git_repo.head()

    monkeypatch.setattr(
        "git_crawl.pipeline.list_org_repositories",
        lambda org, token=None: [_repo_info(local_git_repo.path)],
    )

    result = crawl_org("localorg", cache_dir=tmp_path / "mirrors", state_db=tmp_path / "state.sqlite")

    commit = next(row for row in result.raw_commits if row.sha == raw_author_sha)
    assert commit.author_name == "Original Author"
    assert commit.author_email == "original@example.com"

    file_change = next(row for row in result.file_changes if row.sha == raw_author_sha)
    assert file_change.path == "café.txt"
