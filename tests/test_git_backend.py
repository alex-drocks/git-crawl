import subprocess
from pathlib import Path

import pytest

from git_crawl import git_backend
from git_crawl.github import RepoInfo


def test_read_commit_log_targets_requested_default_branch_ref(monkeypatch):
    calls = []

    def fake_run_git(args, *, cwd=None):
        calls.append(args)
        return ""

    monkeypatch.setattr(git_backend, "_run_git", fake_run_git)

    git_backend.read_commit_log(Path("/tmp/demo.git"), revision="refs/heads/main")

    args = calls[0]
    assert "--all" not in args
    assert "refs/heads/main" in args
    assert "--numstat" in args


def test_read_commit_log_can_still_read_all_refs_when_requested(monkeypatch):
    calls = []

    def fake_run_git(args, *, cwd=None):
        calls.append(args)
        return ""

    monkeypatch.setattr(git_backend, "_run_git", fake_run_git)

    git_backend.read_commit_log(Path("/tmp/demo.git"), all_refs=True)

    args = calls[0]
    assert "--all" in args


def test_get_ref_sha_returns_none_for_missing_refs(monkeypatch):
    calls = []

    def fake_run_git(args, *, cwd=None):
        calls.append(args)
        raise git_backend.GitCommandError("missing ref")

    monkeypatch.setattr(git_backend, "_run_git", fake_run_git)

    assert git_backend.get_ref_sha(Path("/tmp/demo.git"), "refs/heads/main") is None
    assert calls[0][-2:] == ["--verify", "refs/heads/main"]


def test_commit_exists_checks_for_commit_objects(monkeypatch):
    calls = []

    def fake_run_git(args, *, cwd=None):
        calls.append(args)
        return ""

    monkeypatch.setattr(git_backend, "_run_git", fake_run_git)

    assert git_backend.commit_exists(Path("/tmp/demo.git"), "abc123") is True
    assert calls[0][-3:] == ["cat-file", "-e", "abc123^{commit}"]


def test_commit_exists_returns_false_for_missing_objects(monkeypatch):
    def fake_run_git(args, *, cwd=None):
        raise git_backend.GitCommandError("missing object")

    monkeypatch.setattr(git_backend, "_run_git", fake_run_git)

    assert git_backend.commit_exists(Path("/tmp/demo.git"), "abc123") is False


def _repo(full_name: str) -> RepoInfo:
    return RepoInfo(
        name=full_name.rsplit("/", 1)[-1],
        full_name=full_name,
        clone_url=f"https://github.com/{full_name}.git",
        ssh_url=f"git@github.com:{full_name}.git",
        default_branch="main",
        pushed_at="2026-05-01T00:00:00Z",
        archived=False,
        fork=False,
        private=False,
        language="Python",
    )


def test_mirror_path_does_not_collapse_distinct_full_names(tmp_path):
    first = git_backend.mirror_path(tmp_path, _repo("a/b__c"))
    second = git_backend.mirror_path(tmp_path, _repo("a__b/c"))

    assert first != second


def test_run_git_uses_bounded_noninteractive_subprocess(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(git_backend.subprocess, "run", fake_run)

    assert git_backend._run_git(["status"]) == "ok"
    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["timeout"] == git_backend.DEFAULT_GIT_TIMEOUT_SECONDS
    assert captured["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert "BatchMode=yes" in captured["env"]["GIT_SSH_COMMAND"]


def test_git_command_errors_redact_credentials_from_arguments_and_stderr(monkeypatch):
    credentialed_url = "https://sensitive-userinfo@github.com/chutesai/api.git"

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            128,
            stdout="",
            stderr=f"fatal: could not read from {credentialed_url}",
        )

    monkeypatch.setattr(git_backend.subprocess, "run", fake_run)

    with pytest.raises(git_backend.GitCommandError) as exc_info:
        git_backend._run_git(["clone", credentialed_url, "dest"])

    message = str(exc_info.value)
    assert "sensitive-userinfo" not in message
    assert "[REDACTED]" in message


def test_ensure_mirror_retries_existing_mirror_fetch_with_exponential_backoff(monkeypatch, tmp_path):
    repo = _repo("chutesai/api")
    destination = git_backend.mirror_path(tmp_path, repo)
    destination.mkdir(parents=True)
    calls = []
    sleeps = []

    def fake_sleep(policy, failed_attempt, *, override_delay=None, apply_jitter=True):
        sleeps.append(
            policy.delay_for_attempt(
                failed_attempt,
                override_delay=override_delay,
                apply_jitter=apply_jitter,
            )
        )

    monkeypatch.setattr(git_backend, "sleep_before_retry", fake_sleep, raising=False)

    def fake_run_git(args, *, cwd=None):
        calls.append(args)
        if "fetch" in args and sum(1 for call in calls if "fetch" in call) < 3:
            raise git_backend.GitCommandError("temporary network failure")
        return ""

    monkeypatch.setattr(git_backend, "_run_git", fake_run_git)

    assert git_backend.ensure_mirror(
        repo,
        tmp_path,
        max_attempts=3,
        retry_delay=2,
        retry_jitter=0,
    ) == destination
    assert sum(1 for call in calls if "fetch" in call) == 3
    assert sleeps == [2.0, 4.0]


def test_ensure_mirror_clones_into_temporary_path_and_cleans_partial_clone_before_retry(monkeypatch, tmp_path):
    repo = _repo("chutesai/api")
    destination = git_backend.mirror_path(tmp_path, repo)
    clone_destinations = []

    def fake_run_git(args, *, cwd=None):
        if args[:2] != ["clone", "--mirror"]:
            return ""
        clone_destination = Path(args[-1])
        clone_destinations.append(clone_destination)
        assert clone_destination != destination
        if len(clone_destinations) == 1:
            clone_destination.mkdir(parents=True)
            raise git_backend.GitCommandError("clone interrupted")
        assert not clone_destinations[0].exists()
        clone_destination.mkdir(parents=True)
        return ""

    monkeypatch.setattr(git_backend, "_run_git", fake_run_git)

    assert git_backend.ensure_mirror(
        repo,
        tmp_path,
        max_attempts=2,
        retry_delay=0,
        retry_jitter=0,
    ) == destination
    assert len(clone_destinations) == 2
    assert destination.exists()
    assert not any(path.exists() for path in clone_destinations)


def test_ensure_mirror_removes_partial_temporary_clone_after_final_failure(monkeypatch, tmp_path):
    repo = _repo("chutesai/api")
    destination = git_backend.mirror_path(tmp_path, repo)
    clone_destinations = []

    def fake_run_git(args, *, cwd=None):
        if args[:2] == ["clone", "--mirror"]:
            clone_destination = Path(args[-1])
            clone_destinations.append(clone_destination)
            clone_destination.mkdir(parents=True)
            raise git_backend.GitCommandError("clone interrupted")
        return ""

    monkeypatch.setattr(git_backend, "_run_git", fake_run_git)

    with pytest.raises(git_backend.GitCommandError):
        git_backend.ensure_mirror(
            repo,
            tmp_path,
            max_attempts=2,
            retry_delay=0,
            retry_jitter=0,
        )

    assert clone_destinations
    assert not destination.exists()
    assert not any(path.exists() for path in clone_destinations)


def test_ensure_mirror_does_not_remove_destination_created_during_clone_retry(monkeypatch, tmp_path):
    repo = _repo("chutesai/api")
    destination = git_backend.mirror_path(tmp_path, repo)
    marker = destination / "marker"
    clone_attempts = 0

    def fake_run_git(args, *, cwd=None):
        nonlocal clone_attempts
        if args[:2] != ["clone", "--mirror"]:
            return ""
        clone_attempts += 1
        clone_destination = Path(args[-1])
        clone_destination.mkdir(parents=True)
        if clone_attempts == 1:
            destination.mkdir(parents=True)
            marker.write_text("owned by another crawler", encoding="utf-8")
            raise git_backend.GitCommandError("clone interrupted")
        return ""

    monkeypatch.setattr(git_backend, "_run_git", fake_run_git)

    assert git_backend.ensure_mirror(
        repo,
        tmp_path,
        max_attempts=2,
        retry_delay=0,
        retry_jitter=0,
    ) == destination
    assert marker.read_text(encoding="utf-8") == "owned by another crawler"


def test_ensure_mirror_rejects_invalid_destination_created_during_clone_retry(monkeypatch, tmp_path):
    repo = _repo("chutesai/api")
    destination = git_backend.mirror_path(tmp_path, repo)
    marker = destination / "marker"

    def fake_run_git(args, *, cwd=None):
        if args[:2] == ["clone", "--mirror"]:
            clone_destination = Path(args[-1])
            clone_destination.mkdir(parents=True)
            destination.mkdir(parents=True, exist_ok=True)
            marker.write_text("not a git mirror", encoding="utf-8")
            return ""
        if args[-2:] == ["rev-parse", "--git-dir"]:
            raise git_backend.GitCommandError("not a git mirror")
        return ""

    monkeypatch.setattr(git_backend, "_run_git", fake_run_git)

    with pytest.raises(git_backend.GitCommandError, match="not a usable git repository"):
        git_backend.ensure_mirror(
            repo,
            tmp_path,
            max_attempts=1,
            retry_delay=0,
            retry_jitter=0,
        )
    assert marker.read_text(encoding="utf-8") == "not a git mirror"
