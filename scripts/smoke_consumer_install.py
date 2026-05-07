#!/usr/bin/env python3
"""Smoke-test an installed git-crawl wheel from a clean consumer venv.

This is intentionally offline: callers build the wheel first, then this script
installs that wheel into a fresh virtual environment, imports the public package,
and verifies the console entrypoint is available.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: smoke_consumer_install.py DIST_WHEEL", file=sys.stderr)
        return 2

    wheel = Path(args[0]).resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        print(f"wheel does not exist or is not a .whl file: {wheel}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="git-crawl-consumer-") as tmp:
        venv_dir = Path(tmp) / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)
        bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
        python = bin_dir / ("python.exe" if os.name == "nt" else "python")
        git_crawl = bin_dir / ("git-crawl.exe" if os.name == "nt" else "git-crawl")

        _run([str(python), "-m", "pip", "install", "--disable-pip-version-check", str(wheel)])
        import_check = _run(
            [
                str(python),
                "-c",
                (
                    "import json; "
                    "import git_crawl; "
                    "from git_crawl.github import parse_github_repo_url; "
                    "ref = parse_github_repo_url('https://github.com/alex-drocks/git-crawl/tree/main'); "
                    "print(json.dumps({'version': git_crawl.__version__, 'repo': ref.full_name}))"
                ),
            ]
        )
        payload = json.loads(import_check.stdout)
        if payload["repo"] != "alex-drocks/git-crawl":
            raise AssertionError(f"unexpected parsed repo from installed package: {payload}")

        help_result = _run([str(git_crawl), "--help"])
        for expected in ["crawl-org", "crawl-owner", "crawl-repos"]:
            if expected not in help_result.stdout:
                raise AssertionError(f"installed CLI help is missing {expected!r}")
        for removed in ["build-static-api", "dashboard"]:
            if removed in help_result.stdout.lower():
                raise AssertionError(f"installed CLI help still exposes removed reporting surface {removed!r}")

        print(
            json.dumps(
                {
                    "wheel": str(wheel),
                    "version": payload["version"],
                    "repo": payload["repo"],
                    "cli_help_bytes": len(help_result.stdout.encode()),
                },
                sort_keys=True,
            )
        )
    return 0


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"command failed with {completed.returncode}: {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


if __name__ == "__main__":
    raise SystemExit(main())
