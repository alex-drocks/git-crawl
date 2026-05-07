from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@dataclass
class LocalGitRepo:
    """Small helper for integration tests that need real on-disk Git history."""

    path: Path
    _commit_counter: int = field(default=0, init=False)

    def run(self, *args: str, env: dict[str, str] | None = None) -> str:
        git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        git_env.update(env or {})
        completed = subprocess.run(
            ["git", *args],
            cwd=self.path,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=git_env,
        )
        if completed.returncode != 0:
            raise AssertionError(
                f"git {' '.join(args)} failed with {completed.returncode}:\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        return completed.stdout.strip()

    def write_text(self, relative_path: str, content: str) -> Path:
        path = self.path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_bytes(self, relative_path: str, content: bytes) -> Path:
        path = self.path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def rename(self, old_relative_path: str, new_relative_path: str) -> None:
        (self.path / new_relative_path).parent.mkdir(parents=True, exist_ok=True)
        self.run("mv", old_relative_path, new_relative_path)

    def delete(self, relative_path: str) -> None:
        (self.path / relative_path).unlink()

    def checkout(self, branch: str, *, create: bool = False) -> None:
        args = ("checkout", "-b", branch) if create else ("checkout", branch)
        self.run(*args)

    def merge_no_ff(self, branch: str, message: str) -> str:
        env = self._next_commit_env()
        self.run("merge", "--no-ff", branch, "-m", message, env=env)
        return self.head()

    def commit(self, message: str, *, allow_empty: bool = False) -> str:
        self.run("add", "-A")
        env = self._next_commit_env()
        args = ["commit", "-m", message]
        if allow_empty:
            args.insert(1, "--allow-empty")
        self.run(*args, env=env)
        return self.head()

    def head(self, ref: str = "HEAD") -> str:
        return self.run("rev-parse", ref)

    def _next_commit_env(self) -> dict[str, str]:
        self._commit_counter += 1
        timestamp = (datetime(2026, 1, 1, 12, tzinfo=timezone.utc) + timedelta(minutes=self._commit_counter)).isoformat()
        return {
            "GIT_AUTHOR_DATE": timestamp,
            "GIT_COMMITTER_DATE": timestamp,
            "GIT_AUTHOR_NAME": "Integration Tester",
            "GIT_AUTHOR_EMAIL": "tester@example.com",
            "GIT_COMMITTER_NAME": "Integration Tester",
            "GIT_COMMITTER_EMAIL": "tester@example.com",
        }


@pytest.fixture
def local_git_repo(tmp_path: Path) -> LocalGitRepo:
    repo = LocalGitRepo(tmp_path / "source-repo")
    repo.path.mkdir()
    repo.run("init", "-b", "main")
    repo.run("config", "user.name", "Integration Tester")
    repo.run("config", "user.email", "tester@example.com")
    repo.run("config", "commit.gpgsign", "false")
    repo.run("config", "tag.gpgSign", "false")
    return repo
