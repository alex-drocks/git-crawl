from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TypeVar

from .config import CrawlerConfig, load_config
from .github import (
    GitHubAPIError,
    GitHubURLParseError,
    list_repositories_from_urls,
    token_from_env,
)
from .pipeline import (
    REF_SCOPE_ALL_REFS,
    REF_SCOPE_DEFAULT_BRANCH,
    crawl_org,
    crawl_owner,
    crawl_repositories,
    finalize_crawl_state,
    write_crawl_outputs,
)
from .static_api import publish_static_api

T = TypeVar("T")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="git-crawl",
        description="Crawl GitHub repositories and organizations into structured Git metrics outputs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl = subparsers.add_parser("crawl-org", help="crawl one GitHub organization")
    crawl.add_argument("org", nargs="?", help="GitHub organization login, e.g. chutesai")
    crawl.add_argument("--config", help="TOML config file with repeatable crawl settings")
    crawl.add_argument(
        "--output-dir",
        help="directory for structured output files (default: out)",
    )
    crawl.add_argument(
        "--cache-dir",
        help="directory for bare git mirrors (default: .cache/git-crawl)",
    )
    crawl.add_argument(
        "--state-db",
        help="SQLite state database for crawl runs and incremental default-branch heads",
    )
    crawl.add_argument(
        "--active-since",
        help="only crawl repos pushed at or after this ISO timestamp/date",
    )
    crawl.add_argument(
        "--since",
        help="only include commits authored at or after this ISO timestamp/date; unparseable values pass to git",
    )
    crawl.add_argument(
        "--until",
        help="only include commits authored at or before this ISO timestamp/date; unparseable values pass to git",
    )
    crawl.add_argument("--max-repos", type=_positive_int, help="cap number of repos crawled")
    crawl.add_argument(
        "--include-archived",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="include archived repositories",
    )
    crawl.add_argument(
        "--include-forks",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="include fork repositories",
    )
    crawl.add_argument(
        "--prefer-ssh",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="clone discovered repos via SSH instead of HTTPS",
    )
    crawl.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
        help="environment variable containing a GitHub token (default: GITHUB_TOKEN)",
    )
    crawl.add_argument(
        "--format",
        choices=["all", "jsonl", "csv"],
        help="output format to write (default: all)",
    )
    crawl.add_argument(
        "--ref-scope",
        choices=[REF_SCOPE_DEFAULT_BRANCH, REF_SCOPE_ALL_REFS],
        help="git refs to inspect (default: default-branch)",
    )
    crawl.add_argument(
        "--workers",
        type=_positive_int,
        help="maximum repositories to crawl concurrently when --fail-fast is not set (default: 1)",
    )
    crawl.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop the crawl on the first repository failure",
    )

    crawl_owner_parser = subparsers.add_parser("crawl-owner", help="crawl one GitHub owner (organization or user)")
    crawl_owner_parser.add_argument("owner", help="GitHub owner login, e.g. chutesai or torvalds")
    crawl_owner_parser.add_argument("--target", help="crawl target label for output rows/state (default: owner login)")
    crawl_owner_parser.add_argument(
        "--owner-type",
        choices=["auto", "org", "user"],
        default="auto",
        help="owner kind to resolve (default: auto; try org then user)",
    )
    crawl_owner_parser.add_argument(
        "--output-dir",
        help="directory for structured output files (default: out)",
    )
    crawl_owner_parser.add_argument(
        "--cache-dir",
        help="directory for bare git mirrors (default: .cache/git-crawl)",
    )
    crawl_owner_parser.add_argument(
        "--state-db",
        help="SQLite state database for crawl runs and incremental default-branch heads",
    )
    crawl_owner_parser.add_argument(
        "--active-since",
        help="only crawl repos pushed at or after this ISO timestamp/date",
    )
    crawl_owner_parser.add_argument(
        "--since",
        help="only include commits authored at or after this ISO timestamp/date; unparseable values pass to git",
    )
    crawl_owner_parser.add_argument(
        "--until",
        help="only include commits authored at or before this ISO timestamp/date; unparseable values pass to git",
    )
    crawl_owner_parser.add_argument("--max-repos", type=_positive_int, help="cap number of repos crawled")
    crawl_owner_parser.add_argument(
        "--include-archived",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="include archived repositories",
    )
    crawl_owner_parser.add_argument(
        "--include-forks",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="include fork repositories",
    )
    crawl_owner_parser.add_argument(
        "--prefer-ssh",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="clone discovered repos via SSH instead of HTTPS",
    )
    crawl_owner_parser.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
        help="environment variable containing a GitHub token (default: GITHUB_TOKEN)",
    )
    crawl_owner_parser.add_argument(
        "--format",
        choices=["all", "jsonl", "csv"],
        help="output format to write (default: all)",
    )
    crawl_owner_parser.add_argument(
        "--ref-scope",
        choices=[REF_SCOPE_DEFAULT_BRANCH, REF_SCOPE_ALL_REFS],
        help="git refs to inspect (default: default-branch)",
    )
    crawl_owner_parser.add_argument(
        "--workers",
        type=_positive_int,
        help="maximum repositories to crawl concurrently when --fail-fast is not set (default: 1)",
    )
    crawl_owner_parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop the crawl on the first repository failure",
    )

    crawl_repos = subparsers.add_parser("crawl-repos", help="crawl an explicit manifest of GitHub repositories")
    crawl_repos.add_argument("manifest", help="JSON manifest with repository URLs")
    crawl_repos.add_argument("--target", help="crawl target label for output rows (default: manifest target or filename stem)")
    crawl_repos.add_argument(
        "--output-dir",
        help="directory for structured output files (default: out)",
    )
    crawl_repos.add_argument(
        "--cache-dir",
        help="directory for bare git mirrors (default: .cache/git-crawl)",
    )
    crawl_repos.add_argument(
        "--state-db",
        help="SQLite state database for crawl runs and incremental default-branch heads",
    )
    crawl_repos.add_argument(
        "--active-since",
        help="only crawl repos pushed at or after this ISO timestamp/date",
    )
    crawl_repos.add_argument(
        "--since",
        help="only include commits authored at or after this ISO timestamp/date; unparseable values pass to git",
    )
    crawl_repos.add_argument(
        "--until",
        help="only include commits authored at or before this ISO timestamp/date; unparseable values pass to git",
    )
    crawl_repos.add_argument("--max-repos", type=_positive_int, help="cap number of repos crawled")
    crawl_repos.add_argument(
        "--include-archived",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="include archived repositories",
    )
    crawl_repos.add_argument(
        "--include-forks",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="include fork repositories",
    )
    crawl_repos.add_argument(
        "--prefer-ssh",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="clone manifest repos via SSH instead of HTTPS",
    )
    crawl_repos.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
        help="environment variable containing a GitHub token (default: GITHUB_TOKEN)",
    )
    crawl_repos.add_argument(
        "--format",
        choices=["all", "jsonl", "csv"],
        help="output format to write (default: all)",
    )
    crawl_repos.add_argument(
        "--ref-scope",
        choices=[REF_SCOPE_DEFAULT_BRANCH, REF_SCOPE_ALL_REFS],
        help="git refs to inspect (default: default-branch)",
    )
    crawl_repos.add_argument(
        "--workers",
        type=_positive_int,
        help="maximum repositories to crawl concurrently when --fail-fast is not set (default: 1)",
    )
    crawl_repos.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop the crawl on the first repository failure",
    )

    static_api = subparsers.add_parser(
        "build-static-api",
        help="build static API/dashboard files from crawler output",
    )
    static_api.add_argument("org", help="GitHub organization login, e.g. chutesai")
    static_api.add_argument(
        "--data-dir",
        required=True,
        help="directory containing crawler output files to publish",
    )
    static_api.add_argument(
        "--site-dir",
        required=True,
        help="directory to populate with GitHub Pages static API files",
    )
    static_api.add_argument(
        "--run-label",
        default="latest",
        help="published run label/path segment (default: latest)",
    )
    static_api.add_argument(
        "--base-url",
        help="absolute deployed base URL used in generated manifests",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "crawl-owner":
        output_format = _pick(args.format, None, "all")
        state_db = _pick(args.state_db, None, None)
        output_dir = Path(_pick(args.output_dir, None, "out"))
        max_repos = _pick(args.max_repos, None, None)
        workers = _pick(args.workers, None, 1)
        if max_repos is not None and max_repos < 1:
            parser.error("--max-repos must be >= 1")
        if workers < 1:
            parser.error("--workers must be >= 1")
        token = token_from_env(args.token_env)
        try:
            result = crawl_owner(
                args.owner,
                cache_dir=Path(_pick(args.cache_dir, None, ".cache/git-crawl")),
                token=token,
                owner_type=args.owner_type,
                target=args.target,
                active_since=_pick(args.active_since, None, None),
                since=_pick(args.since, None, None),
                until=_pick(args.until, None, None),
                include_archived=_pick(args.include_archived, None, False),
                include_forks=_pick(args.include_forks, None, False),
                max_repos=max_repos,
                prefer_ssh=_pick(args.prefer_ssh, None, False),
                ref_scope=_pick(args.ref_scope, None, REF_SCOPE_DEFAULT_BRANCH),
                state_db=state_db,
                workers=workers,
                fail_fast=args.fail_fast,
                finalize_state=state_db is None,
            )
        except GitHubAPIError as exc:
            print(f"failed to resolve owner repositories: {exc}", file=sys.stderr)
            return 1
        try:
            written = write_crawl_outputs(
                result,
                output_dir,
                write_json=output_format in {"all", "jsonl"},
                write_csv_files=output_format in {"all", "csv"},
            )
        except Exception as exc:  # noqa: BLE001 - CLI should preserve state safety on output failures
            if state_db:
                error_message = _join_errors(result.run.error_message, f"output write failed: {exc}")
                finalize_crawl_state(
                    result,
                    state_db,
                    status="failed",
                    error_message=error_message,
                    update_repo_states=False,
                )
            print(f"failed to write crawl outputs: {exc}", file=sys.stderr)
            return 1

        if state_db:
            result = finalize_crawl_state(result, state_db)
        if args.target:
            print_prefix = f"Crawled {len(result.repositories)} repos for target {result.org} from owner {args.owner}"
        else:
            print_prefix = f"Crawled {len(result.repositories)} repos for owner {result.org}"
        print(
            f"{print_prefix}: "
            f"{len(result.commits)} commits, "
            f"{len(result.file_changes)} file-change rows, "
            f"{len(result.aggregates.org_days)} target-day rows, "
            f"{len(result.aggregates.repo_days)} repo-day rows, "
            f"{len(result.aggregates.contributor_days)} contributor-day rows, "
            f"{len(result.failed_repositories)} repo failures."
        )
        print(f"Run {result.run.run_id}: {result.run.status}")
        if state_db:
            print(
                "State DB active: default-branch crawls emit only commits outside "
                "the matching prior state window."
            )
        for path in written:
            print(path)
        return 0 if result.run.status in {"success", "partial"} else 1

    if args.command == "crawl-repos":
        manifest_target, repo_urls = _load_repository_manifest(Path(args.manifest))
        target = args.target or manifest_target or Path(args.manifest).stem
        output_format = _pick(args.format, None, "all")
        state_db = _pick(args.state_db, None, None)
        output_dir = Path(_pick(args.output_dir, None, "out"))
        max_repos = _pick(args.max_repos, None, None)
        workers = _pick(args.workers, None, 1)
        if max_repos is not None and max_repos < 1:
            parser.error("--max-repos must be >= 1")
        if workers < 1:
            parser.error("--workers must be >= 1")
        token = token_from_env(args.token_env)
        try:
            repositories = list_repositories_from_urls(repo_urls, token=token, max_repos=max_repos)
        except (GitHubAPIError, GitHubURLParseError) as exc:
            print(f"failed to resolve repositories: {exc}", file=sys.stderr)
            return 1
        result = crawl_repositories(
            target,
            repositories,
            cache_dir=Path(_pick(args.cache_dir, None, ".cache/git-crawl")),
            active_since=_pick(args.active_since, None, None),
            since=_pick(args.since, None, None),
            until=_pick(args.until, None, None),
            include_archived=_pick(args.include_archived, None, False),
            include_forks=_pick(args.include_forks, None, False),
            max_repos=max_repos,
            prefer_ssh=_pick(args.prefer_ssh, None, False),
            ref_scope=_pick(args.ref_scope, None, REF_SCOPE_DEFAULT_BRANCH),
            state_db=state_db,
            workers=workers,
            fail_fast=args.fail_fast,
            finalize_state=state_db is None,
        )
        try:
            written = write_crawl_outputs(
                result,
                output_dir,
                write_json=output_format in {"all", "jsonl"},
                write_csv_files=output_format in {"all", "csv"},
            )
        except Exception as exc:  # noqa: BLE001 - CLI should preserve state safety on output failures
            if state_db:
                error_message = _join_errors(result.run.error_message, f"output write failed: {exc}")
                finalize_crawl_state(
                    result,
                    state_db,
                    status="failed",
                    error_message=error_message,
                    update_repo_states=False,
                )
            print(f"failed to write crawl outputs: {exc}", file=sys.stderr)
            return 1

        if state_db:
            result = finalize_crawl_state(result, state_db)
        print(
            f"Crawled {len(result.repositories)} repos for {result.org}: "
            f"{len(result.commits)} commits, "
            f"{len(result.file_changes)} file-change rows, "
            f"{len(result.aggregates.org_days)} target-day rows, "
            f"{len(result.aggregates.repo_days)} repo-day rows, "
            f"{len(result.aggregates.contributor_days)} contributor-day rows, "
            f"{len(result.failed_repositories)} repo failures."
        )
        print(f"Run {result.run.run_id}: {result.run.status}")
        if state_db:
            print(
                "State DB active: default-branch crawls emit only commits outside "
                "the matching prior state window."
            )
        for path in written:
            print(path)
        return 0 if result.run.status in {"success", "partial"} else 1

    if args.command == "build-static-api":
        result = publish_static_api(
            org=args.org,
            data_dir=Path(args.data_dir),
            site_dir=Path(args.site_dir),
            run_label=args.run_label,
            base_url=args.base_url,
        )
        print(f"Published static API for {args.org} at {result.dataset_dir}")
        for path in [*result.copied_files, *result.manifest_files, *result.dashboard_files]:
            print(path)
        return 0

    if args.command == "crawl-org":
        config = load_config(args.config) if args.config else CrawlerConfig()
        org = args.org or config.org
        if not org:
            parser.error("crawl-org requires an org argument or org in --config")

        output_format = _pick(args.format, config.output_format, "all")
        state_db = _pick(args.state_db, config.state_db, None)
        output_dir = Path(_pick(args.output_dir, config.output_dir, "out"))
        max_repos = _pick(args.max_repos, config.max_repos, None)
        workers = _pick(args.workers, config.workers, 1)
        if max_repos is not None and max_repos < 1:
            parser.error("--max-repos must be >= 1")
        if workers < 1:
            parser.error("--workers must be >= 1")
        token = token_from_env(args.token_env)
        result = crawl_org(
            org,
            cache_dir=Path(_pick(args.cache_dir, config.cache_dir, ".cache/git-crawl")),
            token=token,
            active_since=_pick(args.active_since, config.active_since, None),
            since=_pick(args.since, config.since, None),
            until=_pick(args.until, config.until, None),
            include_archived=_pick(args.include_archived, config.include_archived, False),
            include_forks=_pick(args.include_forks, config.include_forks, False),
            max_repos=max_repos,
            prefer_ssh=_pick(args.prefer_ssh, None, False),
            ref_scope=_pick(args.ref_scope, config.ref_scope, REF_SCOPE_DEFAULT_BRANCH),
            state_db=state_db,
            workers=workers,
            fail_fast=args.fail_fast,
            finalize_state=state_db is None,
        )
        try:
            written = write_crawl_outputs(
                result,
                output_dir,
                write_json=output_format in {"all", "jsonl"},
                write_csv_files=output_format in {"all", "csv"},
            )
        except Exception as exc:  # noqa: BLE001 - CLI should preserve state safety on output failures
            if state_db:
                error_message = _join_errors(result.run.error_message, f"output write failed: {exc}")
                finalize_crawl_state(
                    result,
                    state_db,
                    status="failed",
                    error_message=error_message,
                    update_repo_states=False,
                )
            print(f"failed to write crawl outputs: {exc}", file=sys.stderr)
            return 1

        if state_db:
            result = finalize_crawl_state(result, state_db)
        print(
            f"Crawled {len(result.repositories)} repos from {result.org}: "
            f"{len(result.commits)} commits, "
            f"{len(result.file_changes)} file-change rows, "
            f"{len(result.aggregates.org_days)} org-day rows, "
            f"{len(result.aggregates.repo_days)} repo-day rows, "
            f"{len(result.aggregates.contributor_days)} contributor-day rows, "
            f"{len(result.failed_repositories)} repo failures."
        )
        print(f"Run {result.run.run_id}: {result.run.status}")
        if state_db:
            print(
                "State DB active: default-branch crawls emit only commits outside "
                "the matching prior state window."
            )
        for path in written:
            print(path)
        return 0 if result.run.status in {"success", "partial"} else 1

    parser.error(f"Unknown command {args.command!r}")
    return 2


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def _pick(cli_value: T | None, config_value: T | None, default: T) -> T:
    if cli_value is not None:
        return cli_value
    if config_value is not None:
        return config_value
    return default


def _join_errors(*messages: str | None) -> str:
    return "; ".join(message for message in messages if message)


def _load_repository_manifest(path: Path) -> tuple[str | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"failed to read repository manifest {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"repository manifest {path} is not valid JSON: {exc}") from exc

    target: str | None = None
    raw_repositories: object
    if isinstance(payload, list):
        raw_repositories = payload
    elif isinstance(payload, dict):
        target_value = payload.get("target")
        target = str(target_value) if target_value else None
        raw_repositories = payload.get("repositories", payload.get("repos", []))
    else:
        raise SystemExit("repository manifest must be a JSON object or array")

    if not isinstance(raw_repositories, list) or not raw_repositories:
        raise SystemExit("repository manifest must contain at least one repository URL")

    urls = [_repository_url_from_manifest_entry(entry) for entry in raw_repositories]
    return target, urls


def _repository_url_from_manifest_entry(entry: object) -> str:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict) and isinstance(entry.get("url"), str):
        return entry["url"]
    raise SystemExit("repository manifest entries must be URL strings or objects with a string 'url' field")


if __name__ == "__main__":
    raise SystemExit(main())
