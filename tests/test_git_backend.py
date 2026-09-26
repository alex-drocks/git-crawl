import os
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
    assert "-z" in args
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
        if args[:2] != ["clone", "--bare"]:
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
        if args[:2] == ["clone", "--bare"]:
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
        if args[:2] != ["clone", "--bare"]:
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
        if args[:2] == ["clone", "--bare"]:
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


def test_run_git_decodes_invalid_utf8_output_and_keeps_carriage_returns(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        if command[-1] == "fail":
            return subprocess.CompletedProcess(command, 128, stdout=b"", stderr=b"fatal: bad \xff byte")
        return subprocess.CompletedProcess(command, 0, stdout=b"caf\xe9.txt\r\nok\n", stderr=b"")

    monkeypatch.setattr(git_backend.subprocess, "run", fake_run)

    assert git_backend._run_git(["log"]) == "caf�.txt\r\nok\n"
    assert "text" not in captured
    with pytest.raises(git_backend.GitCommandError, match="fatal: bad � byte"):
        git_backend._run_git(["fail"])


def test_ensure_mirror_fetches_only_branches_and_tags_into_existing_mirror(monkeypatch, tmp_path):
    repo = _repo("chutesai/api")
    destination = git_backend.mirror_path(tmp_path, repo)
    destination.mkdir(parents=True)
    calls = []

    def fake_run_git(args, *, cwd=None, stdin_text=None):
        calls.append(args)
        if args[-3:] == ["config", "--get-all", "remote.origin.fetch"]:
            return "\n".join(git_backend.MIRROR_FETCH_REFSPECS) + "\n"
        if "for-each-ref" in args:
            return "refs/heads/main\nrefs/tags/v1\n"
        return ""

    monkeypatch.setattr(git_backend, "_run_git", fake_run_git)

    assert git_backend.ensure_mirror(repo, tmp_path) == destination
    fetch = next(call for call in calls if "fetch" in call)
    assert fetch[-3:] == ["origin", *git_backend.MIRROR_FETCH_REFSPECS]
    assert "--prune" in fetch
    # An already-limited mirror is not reconfigured or pruned on every run.
    assert not any("--replace-all" in call or "update-ref" in call for call in calls)


def test_ensure_mirror_default_retries_ride_out_a_longer_network_outage(monkeypatch, tmp_path):
    repo = _repo("chutesai/api")
    destination = git_backend.mirror_path(tmp_path, repo)
    destination.mkdir(parents=True)
    retries = []
    fetches = []

    def fake_sleep(policy, failed_attempt, *, override_delay=None, apply_jitter=True):
        retries.append((policy, failed_attempt))

    def fake_run_git(args, *, cwd=None, stdin_text=None):
        if "fetch" in args:
            fetches.append(args)
            if len(fetches) < 5:
                raise git_backend.GitCommandError("temporary network failure")
        return ""

    monkeypatch.setattr(git_backend, "sleep_before_retry", fake_sleep)
    monkeypatch.setattr(git_backend, "_run_git", fake_run_git)

    assert git_backend.ensure_mirror(repo, tmp_path) == destination
    assert len(fetches) == 5
    policy = retries[0][0]
    assert (policy.max_attempts, policy.initial_delay) == (5, 2.0)
    assert [policy.delay_for_attempt(attempt, apply_jitter=False) for _, attempt in retries] == [2.0, 4.0, 8.0, 16.0]


def _git(*args: str, cwd: Path | None = None) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    completed = subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True, env=env)
    return completed.stdout


def _local_repo_info(source: Path) -> RepoInfo:
    return RepoInfo(
        name="demo",
        full_name="localorg/demo",
        clone_url=str(source),
        ssh_url=str(source),
        default_branch="main",
        pushed_at="2026-01-10T00:00:00Z",
        archived=False,
        fork=False,
        private=False,
        language="Python",
    )


def _mirror_refs(mirror: Path) -> list[str]:
    return _git("--git-dir", str(mirror), "for-each-ref", "--format=%(refname)").split()


def _add_pull_request_ref(local_git_repo, number: int) -> str:
    """Point refs/pull/<number>/head at an unmerged commit, as GitHub advertises it."""
    local_git_repo.checkout(f"pr-{number}", create=True)
    local_git_repo.write_text(f"src/pr_{number}.py", "UNMERGED = True\n")
    pull_sha = local_git_repo.commit(f"unmerged pull request {number}")
    local_git_repo.checkout("main")
    local_git_repo.run("update-ref", f"refs/pull/{number}/head", pull_sha)
    local_git_repo.run("branch", "-D", f"pr-{number}")
    return pull_sha


def test_new_mirror_caches_branches_and_tags_but_not_pull_request_refs(tmp_path, local_git_repo):
    local_git_repo.write_text("src/app.py", "print('hello')\n")
    local_git_repo.commit("initial app")
    local_git_repo.run("tag", "v1")
    _add_pull_request_ref(local_git_repo, 1)

    mirror = git_backend.ensure_mirror(_local_repo_info(local_git_repo.path), tmp_path / "mirrors")

    assert _mirror_refs(mirror) == ["refs/heads/main", "refs/tags/v1"]
    assert _git("--git-dir", str(mirror), "config", "--get-all", "remote.origin.fetch").split() == list(
        git_backend.MIRROR_FETCH_REFSPECS
    )

    _add_pull_request_ref(local_git_repo, 2)
    local_git_repo.checkout("feature", create=True)
    local_git_repo.commit("feature work", allow_empty=True)
    local_git_repo.checkout("main")
    git_backend.ensure_mirror(_local_repo_info(local_git_repo.path), tmp_path / "mirrors")

    assert _mirror_refs(mirror) == ["refs/heads/feature", "refs/heads/main", "refs/tags/v1"]


def test_ensure_mirror_upgrades_mirror_clones_from_earlier_versions(tmp_path, local_git_repo):
    local_git_repo.write_text("src/app.py", "print('hello')\n")
    local_git_repo.commit("initial app")
    _add_pull_request_ref(local_git_repo, 1)
    repo = _local_repo_info(local_git_repo.path)
    mirror = git_backend.mirror_path(tmp_path, repo)
    # git-crawl 0.3.2 and earlier cached repositories with `git clone --mirror`.
    _git("clone", "--quiet", "--mirror", str(local_git_repo.path), str(mirror))
    assert "refs/pull/1/head" in _mirror_refs(mirror)

    assert git_backend.ensure_mirror(repo, tmp_path) == mirror

    assert _mirror_refs(mirror) == ["refs/heads/main"]
    assert _git("--git-dir", str(mirror), "config", "--get-all", "remote.origin.fetch").split() == list(
        git_backend.MIRROR_FETCH_REFSPECS
    )
    with pytest.raises(subprocess.CalledProcessError):
        _git("--git-dir", str(mirror), "config", "--get", "remote.origin.mirror")
