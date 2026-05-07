from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path
from urllib.parse import quote

from .github import RepoInfo
from .gitlog import GIT_LOG_FORMAT
from .redaction import redact_text
from .retry import RetryPolicy, sleep_before_retry

DEFAULT_GIT_TIMEOUT_SECONDS = 300


class GitCommandError(RuntimeError):
    pass


def _run_git(args: list[str], *, cwd: str | Path | None = None) -> str:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "true"
    ssh_command = env.get("GIT_SSH_COMMAND", "ssh")
    if "BatchMode" not in ssh_command:
        ssh_command = f"{ssh_command} -oBatchMode=yes"
    if "ConnectTimeout" not in ssh_command:
        ssh_command = f"{ssh_command} -oConnectTimeout=30"
    env["GIT_SSH_COMMAND"] = ssh_command
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            text=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=DEFAULT_GIT_TIMEOUT_SECONDS,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitCommandError(
            redact_text(f"git {' '.join(args)} timed out after {DEFAULT_GIT_TIMEOUT_SECONDS} seconds")
        ) from exc
    if completed.returncode != 0:
        raise GitCommandError(
            redact_text(f"git {' '.join(args)} failed with {completed.returncode}: {completed.stderr.strip()}")
        )
    return completed.stdout


def _run_git_with_retries(args: list[str], *, retry_policy: RetryPolicy) -> str:
    last_error: GitCommandError | None = None
    for attempt in range(1, retry_policy.max_attempts + 1):
        try:
            return _run_git(args)
        except GitCommandError as error:
            last_error = error
            if attempt >= retry_policy.max_attempts:
                raise
            sleep_before_retry(retry_policy, attempt)
    raise GitCommandError(str(last_error))


def mirror_path(cache_dir: str | Path, repo: RepoInfo) -> Path:
    return Path(cache_dir) / f"{quote(repo.full_name, safe='')}.git"


def ensure_mirror(
    repo: RepoInfo,
    cache_dir: str | Path,
    *,
    prefer_ssh: bool = False,
    max_attempts: int = 3,
    retry_delay: float = 1.0,
    retry_max_delay: float = 60.0,
    retry_jitter: float = 0.25,
) -> Path:
    """Create or update a bare mirror clone for a repository."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = mirror_path(cache_dir, repo)
    remote_url = repo.ssh_url if prefer_ssh else repo.clone_url
    retry_policy = RetryPolicy(
        max_attempts=max_attempts,
        initial_delay=retry_delay,
        max_delay=retry_max_delay,
        jitter=retry_jitter,
    )

    if destination.exists():
        _run_git(["--git-dir", str(destination), "remote", "set-url", "origin", remote_url])
        _run_git_with_retries(
            ["--git-dir", str(destination), "fetch", "--prune", "--tags", "origin"],
            retry_policy=retry_policy,
        )
    else:
        _clone_mirror_with_retries(
            remote_url,
            destination=destination,
            retry_policy=retry_policy,
        )

    return destination


def _clone_mirror_with_retries(remote_url: str, *, destination: Path, retry_policy: RetryPolicy) -> None:
    for attempt in range(1, retry_policy.max_attempts + 1):
        temp_destination = _temporary_mirror_path(destination, attempt)
        _remove_partial_clone(temp_destination)
        try:
            _run_git(["clone", "--mirror", remote_url, str(temp_destination)])
            _install_cloned_mirror(temp_destination, destination)
            return
        except GitCommandError:
            _remove_partial_clone(temp_destination)
            if attempt >= retry_policy.max_attempts:
                raise
            sleep_before_retry(retry_policy, attempt)
        except Exception:
            _remove_partial_clone(temp_destination)
            raise


def _temporary_mirror_path(destination: Path, attempt: int) -> Path:
    return destination.with_name(f".{destination.name}.tmp-{os.getpid()}-{attempt}-{uuid.uuid4().hex}")


def _install_cloned_mirror(temp_destination: Path, destination: Path) -> None:
    try:
        destination.mkdir()
    except FileExistsError:
        _remove_partial_clone(temp_destination)
        _validate_existing_mirror(destination)
        return

    try:
        for child in temp_destination.iterdir():
            shutil.move(str(child), str(destination / child.name))
        _remove_partial_clone(temp_destination)
    except Exception:
        _remove_partial_clone(destination)
        _remove_partial_clone(temp_destination)
        raise


def _validate_existing_mirror(destination: Path) -> None:
    try:
        _run_git(["--git-dir", str(destination), "rev-parse", "--git-dir"])
    except GitCommandError as error:
        raise GitCommandError(f"existing mirror at {destination} is not a usable git repository") from error


def _remove_partial_clone(destination: Path) -> None:
    if not destination.exists():
        return
    if destination.is_dir():
        shutil.rmtree(destination)
    else:
        destination.unlink()


def get_ref_sha(mirror: str | Path, ref: str) -> str | None:
    """Return the SHA for a ref in a bare mirror, or None if the ref is absent."""
    try:
        return _run_git(["--git-dir", str(mirror), "rev-parse", "--verify", ref]).strip()
    except GitCommandError:
        return None


def commit_exists(mirror: str | Path, sha: str) -> bool:
    """Return true when a commit object is available in a bare mirror."""
    try:
        _run_git(["--git-dir", str(mirror), "cat-file", "-e", f"{sha}^{{commit}}"])
        return True
    except GitCommandError:
        return False


def read_commit_log(
    mirror: str | Path,
    *,
    since: str | None = None,
    until: str | None = None,
    revision: str | None = None,
    all_refs: bool = False,
) -> str:
    """Read commit history with per-file numstat data from a bare mirror."""
    if revision and all_refs:
        raise ValueError("Use either revision or all_refs, not both")

    args = [
        "-c",
        "core.quotePath=false",
        "--git-dir",
        str(mirror),
        "log",
        "--numstat",
        "--date=iso-strict",
        f"--format=format:{GIT_LOG_FORMAT}",
    ]
    if all_refs:
        args.append("--all")
    elif revision:
        args.append(revision)
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")

    try:
        return _run_git(args)
    except GitCommandError as exc:
        message = str(exc).lower()
        if "does not have any commits" in message or "bad default revision" in message:
            return ""
        raise
