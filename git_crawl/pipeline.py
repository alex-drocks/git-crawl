from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .git_backend import commit_exists, ensure_mirror, get_ref_sha, read_commit_log
from .github import RepoInfo, RepositoryExclusion, list_org_repositories, partition_repositories
from .gitlog import CommitRecord, parse_git_log
from .metrics import AggregateResult, aggregate_daily
from .output import write_csv, write_jsonl
from .raw import CommitRow, FileChangeRow, build_raw_rows
from .redaction import redact_text, redact_url_credentials
from .state import (
    CURRENT_REPO_STATE_SEMANTICS_VERSION,
    LEGACY_UNKNOWN_HISTORY_WINDOW,
    CrawlRunRecord,
    CrawlStateStore,
    RepoState,
    utc_now,
)

REF_SCOPE_DEFAULT_BRANCH = "default-branch"
REF_SCOPE_ALL_REFS = "all-refs"
REF_SCOPES = {REF_SCOPE_DEFAULT_BRANCH, REF_SCOPE_ALL_REFS}

REPO_DAY_FIELDS = [
    "run_id",
    "org",
    "repo",
    "date",
    "commits",
    "unique_contributors",
    "lines_added",
    "lines_deleted",
    "files_changed",
]
ORG_DAY_FIELDS = [
    "run_id",
    "org",
    "date",
    "commits",
    "unique_contributors",
    "lines_added",
    "lines_deleted",
    "files_changed",
]
CONTRIBUTOR_DAY_FIELDS = [
    "run_id",
    "org",
    "repo",
    "date",
    "author_name",
    "author_email",
    "author_login",
    "commits",
    "lines_added",
    "lines_deleted",
    "files_changed",
]
REPOSITORY_FIELDS = [
    "run_id",
    "org",
    "name",
    "full_name",
    "clone_url",
    "ssh_url",
    "default_branch",
    "pushed_at",
    "archived",
    "fork",
    "private",
    "language",
]
CRAWL_RUN_FIELDS = [
    "run_id",
    "org",
    "started_at",
    "finished_at",
    "status",
    "ref_scope",
    "history_since",
    "history_until",
    "active_since",
    "repositories_discovered",
    "repositories_selected",
    "repositories_crawled",
    "repositories_failed",
    "commits_parsed",
    "error_message",
]
COMMIT_FIELDS = [
    "run_id",
    "org",
    "repo",
    "sha",
    "parents",
    "parent_count",
    "is_merge_commit",
    "author_name",
    "author_email",
    "author_login",
    "authored_at",
    "files_changed",
    "lines_added",
    "lines_deleted",
]
FILE_CHANGE_FIELDS = [
    "run_id",
    "org",
    "repo",
    "sha",
    "path",
    "additions",
    "deletions",
    "is_binary",
    "path_class",
    "is_generated_like",
    "is_lockfile",
]
REPO_FAILURE_FIELDS = [
    "run_id",
    "org",
    "repo",
    "full_name",
    "error",
]
EXCLUDED_REPOSITORY_FIELDS = [
    "run_id",
    "org",
    "name",
    "full_name",
    "clone_url",
    "ssh_url",
    "default_branch",
    "pushed_at",
    "archived",
    "fork",
    "private",
    "language",
    "exclusion_reason",
]


@dataclass(frozen=True)
class RepoFailure:
    run_id: str
    org: str
    repo: str
    full_name: str
    error: str


@dataclass(frozen=True)
class RepositoryRow:
    run_id: str
    org: str
    name: str
    full_name: str
    clone_url: str
    ssh_url: str
    default_branch: str
    pushed_at: str | None
    archived: bool
    fork: bool
    private: bool
    language: str | None


@dataclass(frozen=True)
class ExcludedRepositoryRow:
    run_id: str
    org: str
    name: str
    full_name: str
    clone_url: str
    ssh_url: str
    default_branch: str
    pushed_at: str | None
    archived: bool
    fork: bool
    private: bool
    language: str | None
    exclusion_reason: str


@dataclass(frozen=True)
class RepoStateUpdate:
    repo: str
    default_branch: str
    last_ref_sha: str


@dataclass(frozen=True)
class _RepoCrawlResult:
    repo: RepoInfo
    commits: list[CommitRecord]
    ref_sha: str | None
    repo_key: str


@dataclass(frozen=True)
class CrawlResult:
    org: str
    run: CrawlRunRecord
    repositories: list[RepoInfo]
    commits: list[CommitRecord]
    raw_commits: list[CommitRow]
    file_changes: list[FileChangeRow]
    failed_repositories: list[RepoFailure]
    repo_state_updates: list[RepoStateUpdate]
    aggregates: AggregateResult
    excluded_repositories: list[ExcludedRepositoryRow] = field(default_factory=list)


def crawl_org(
    org: str,
    *,
    cache_dir: str | Path,
    token: str | None = None,
    active_since: str | None = None,
    since: str | None = None,
    until: str | None = None,
    include_archived: bool = False,
    include_forks: bool = False,
    max_repos: int | None = None,
    prefer_ssh: bool = False,
    ref_scope: str = REF_SCOPE_DEFAULT_BRANCH,
    state_db: str | Path | None = None,
    workers: int = 1,
    fail_fast: bool = False,
    finalize_state: bool = True,
) -> CrawlResult:
    """Crawl selected public repositories for one GitHub org and aggregate git history."""
    if ref_scope not in REF_SCOPES:
        raise ValueError(f"Unsupported ref_scope {ref_scope!r}; expected one of {sorted(REF_SCOPES)}")
    if workers < 1:
        raise ValueError("workers must be >= 1")
    if max_repos is not None and max_repos < 1:
        raise ValueError("max_repos must be >= 1")

    store = CrawlStateStore(state_db) if state_db else None
    run = _start_run(store, org=org, ref_scope=ref_scope, since=since, until=until, active_since=active_since)

    try:
        discovered = list_org_repositories(org, token=token)
        repositories, excluded = partition_repositories(
            discovered,
            active_since=active_since,
            include_archived=include_archived,
            include_forks=include_forks,
            max_repos=max_repos,
        )
        excluded_repositories = _build_excluded_repository_rows(
            org=org,
            run_id=run.run_id,
            exclusions=excluded,
        )

        previous_states = {
            repo.name: store.get_repo_state(org=org, repo=repo.name) if store else None
            for repo in repositories
        }
        repo_results: list[_RepoCrawlResult] = []
        failed_repositories: list[RepoFailure] = []

        def crawl_one(repo: RepoInfo) -> _RepoCrawlResult:
            return _crawl_repository(
                repo,
                cache_dir=cache_dir,
                prefer_ssh=prefer_ssh,
                ref_scope=ref_scope,
                previous_state=previous_states.get(repo.name),
                since=since,
                until=until,
            )

        if fail_fast or workers == 1 or len(repositories) <= 1:
            for repo in repositories:
                try:
                    repo_results.append(crawl_one(repo))
                except Exception as exc:  # noqa: BLE001 - serialized into run report
                    failure = RepoFailure(run.run_id, org, repo.name, repo.full_name, redact_text(exc))
                    failed_repositories.append(failure)
                    if fail_fast:
                        break
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(crawl_one, repo): repo for repo in repositories}
                for future in as_completed(futures):
                    repo = futures[future]
                    try:
                        repo_results.append(future.result())
                    except Exception as exc:  # noqa: BLE001 - serialized into run report
                        failure = RepoFailure(run.run_id, org, repo.name, repo.full_name, redact_text(exc))
                        failed_repositories.append(failure)
                        if fail_fast:
                            for pending in futures:
                                pending.cancel()
                            break

        repo_order = {repo.name: index for index, repo in enumerate(repositories)}
        repo_results.sort(key=lambda result: repo_order[result.repo.name])
        failed_repositories.sort(key=lambda failure: repo_order.get(failure.repo, len(repo_order)))

        commits = [commit for result in repo_results for commit in result.commits]
        raw_commits, file_changes = build_raw_rows(org=org, run_id=run.run_id, commits=commits)
        aggregates = aggregate_daily(org, commits)
        repo_state_updates = _build_repo_state_updates(ref_scope=ref_scope, repo_results=repo_results)

        if fail_fast and failed_repositories:
            status = "failed"
        elif failed_repositories and not repo_results and repositories:
            status = "failed"
        elif failed_repositories:
            status = "partial"
        else:
            status = "success"

        if store and finalize_state:
            _persist_repo_state_updates(
                store,
                org=org,
                run_id=run.run_id,
                history_since=since,
                history_until=until,
                updates=repo_state_updates,
            )
        run = _finish_run(
            store if finalize_state else None,
            run,
            status=status,
            repositories_discovered=len(discovered),
            repositories_selected=len(repositories),
            repositories_crawled=len(repo_results),
            repositories_failed=len(failed_repositories),
            commits_parsed=len(commits),
            error_message="; ".join(f"{failure.full_name}: {failure.error}" for failure in failed_repositories) or None,
        )

        return CrawlResult(
            org=org,
            run=run,
            repositories=repositories,
            commits=commits,
            raw_commits=raw_commits,
            file_changes=file_changes,
            failed_repositories=failed_repositories,
            repo_state_updates=repo_state_updates,
            aggregates=aggregates,
            excluded_repositories=excluded_repositories,
        )
    except Exception as exc:
        _finish_run(
            store,
            run,
            status="failed",
            repositories_discovered=0,
            repositories_selected=0,
            repositories_crawled=0,
            repositories_failed=0,
            commits_parsed=0,
            error_message=redact_text(exc),
        )
        raise


def crawl_repositories(
    target: str,
    repositories: list[RepoInfo],
    *,
    cache_dir: str | Path,
    active_since: str | None = None,
    since: str | None = None,
    until: str | None = None,
    include_archived: bool = False,
    include_forks: bool = False,
    max_repos: int | None = None,
    prefer_ssh: bool = False,
    ref_scope: str = REF_SCOPE_DEFAULT_BRANCH,
    state_db: str | Path | None = None,
    workers: int = 1,
    fail_fast: bool = False,
    finalize_state: bool = True,
) -> CrawlResult:
    """Crawl an explicit repository set under a caller-defined target label.

    Unlike ``crawl_org``, repository identity is the stable ``owner/repo`` full
    name. This avoids collisions when a manifest contains repos with the same
    short name under different owners.
    """
    if ref_scope not in REF_SCOPES:
        raise ValueError(f"Unsupported ref_scope {ref_scope!r}; expected one of {sorted(REF_SCOPES)}")
    if workers < 1:
        raise ValueError("workers must be >= 1")
    if max_repos is not None and max_repos < 1:
        raise ValueError("max_repos must be >= 1")

    store = CrawlStateStore(state_db) if state_db else None
    run = _start_run(store, org=target, ref_scope=ref_scope, since=since, until=until, active_since=active_since)

    try:
        discovered = _dedupe_repositories_by_full_name(repositories)
        selected_repositories, excluded = partition_repositories(
            discovered,
            active_since=active_since,
            include_archived=include_archived,
            include_forks=include_forks,
            max_repos=max_repos,
        )
        excluded_repositories = _build_excluded_repository_rows(
            org=target,
            run_id=run.run_id,
            exclusions=excluded,
        )

        previous_states = {
            repo.full_name: store.get_repo_state(org=target, repo=repo.full_name) if store else None
            for repo in selected_repositories
        }
        repo_results: list[_RepoCrawlResult] = []
        failed_repositories: list[RepoFailure] = []

        def crawl_one(repo: RepoInfo) -> _RepoCrawlResult:
            return _crawl_repository(
                repo,
                cache_dir=cache_dir,
                prefer_ssh=prefer_ssh,
                ref_scope=ref_scope,
                previous_state=previous_states.get(repo.full_name),
                since=since,
                until=until,
                repo_key=repo.full_name,
            )

        if fail_fast or workers == 1 or len(selected_repositories) <= 1:
            for repo in selected_repositories:
                try:
                    repo_results.append(crawl_one(repo))
                except Exception as exc:  # noqa: BLE001 - serialized into run report
                    failure = RepoFailure(run.run_id, target, repo.full_name, repo.full_name, redact_text(exc))
                    failed_repositories.append(failure)
                    if fail_fast:
                        break
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(crawl_one, repo): repo for repo in selected_repositories}
                for future in as_completed(futures):
                    repo = futures[future]
                    try:
                        repo_results.append(future.result())
                    except Exception as exc:  # noqa: BLE001 - serialized into run report
                        failure = RepoFailure(run.run_id, target, repo.full_name, repo.full_name, redact_text(exc))
                        failed_repositories.append(failure)
                        if fail_fast:
                            for pending in futures:
                                pending.cancel()
                            break

        repo_order = {repo.full_name: index for index, repo in enumerate(selected_repositories)}
        repo_results.sort(key=lambda result: repo_order[result.repo.full_name])
        failed_repositories.sort(key=lambda failure: repo_order.get(failure.repo, len(repo_order)))

        commits = [commit for result in repo_results for commit in result.commits]
        raw_commits, file_changes = build_raw_rows(org=target, run_id=run.run_id, commits=commits)
        aggregates = aggregate_daily(target, commits)
        repo_state_updates = _build_repo_state_updates(ref_scope=ref_scope, repo_results=repo_results)

        if fail_fast and failed_repositories:
            status = "failed"
        elif failed_repositories and not repo_results and selected_repositories:
            status = "failed"
        elif failed_repositories:
            status = "partial"
        else:
            status = "success"

        if store and finalize_state:
            _persist_repo_state_updates(
                store,
                org=target,
                run_id=run.run_id,
                history_since=since,
                history_until=until,
                updates=repo_state_updates,
            )
        run = _finish_run(
            store if finalize_state else None,
            run,
            status=status,
            repositories_discovered=len(discovered),
            repositories_selected=len(selected_repositories),
            repositories_crawled=len(repo_results),
            repositories_failed=len(failed_repositories),
            commits_parsed=len(commits),
            error_message="; ".join(f"{failure.full_name}: {failure.error}" for failure in failed_repositories) or None,
        )

        return CrawlResult(
            org=target,
            run=run,
            repositories=selected_repositories,
            commits=commits,
            raw_commits=raw_commits,
            file_changes=file_changes,
            failed_repositories=failed_repositories,
            repo_state_updates=repo_state_updates,
            aggregates=aggregates,
            excluded_repositories=excluded_repositories,
        )
    except Exception as exc:
        _finish_run(
            store,
            run,
            status="failed",
            repositories_discovered=0,
            repositories_selected=0,
            repositories_crawled=0,
            repositories_failed=0,
            commits_parsed=0,
            error_message=redact_text(exc),
        )
        raise


def _dedupe_repositories_by_full_name(repositories: list[RepoInfo]) -> list[RepoInfo]:
    deduped: list[RepoInfo] = []
    seen: set[str] = set()
    for repo in repositories:
        if repo.full_name in seen:
            continue
        deduped.append(repo)
        seen.add(repo.full_name)
    return deduped


def _crawl_repository(
    repo: RepoInfo,
    *,
    cache_dir: str | Path,
    prefer_ssh: bool,
    ref_scope: str,
    previous_state: RepoState | None,
    since: str | None,
    until: str | None,
    repo_key: str | None = None,
) -> _RepoCrawlResult:
    repo_key = repo_key or repo.name
    mirror = ensure_mirror(repo, cache_dir=cache_dir, prefer_ssh=prefer_ssh)
    revision: str | None = None
    all_refs = False
    current_ref_sha: str | None = None

    if ref_scope == REF_SCOPE_DEFAULT_BRANCH:
        default_ref = f"refs/heads/{repo.default_branch}"
        current_ref_sha = get_ref_sha(mirror, default_ref)
        if current_ref_sha is None:
            return _RepoCrawlResult(repo=repo, commits=[], ref_sha=None, repo_key=repo_key)

        matching_previous_state = (
            previous_state
            if _previous_state_matches_scope(
                previous_state,
                default_branch=repo.default_branch,
                history_since=since,
                history_until=until,
            )
            else None
        )
        if matching_previous_state and matching_previous_state.last_ref_sha == current_ref_sha:
            return _RepoCrawlResult(repo=repo, commits=[], ref_sha=current_ref_sha, repo_key=repo_key)
        if (
            matching_previous_state
            and matching_previous_state.last_ref_sha
            and commit_exists(mirror, matching_previous_state.last_ref_sha)
        ):
            revision = f"{matching_previous_state.last_ref_sha}..{current_ref_sha}"
        else:
            revision = default_ref
    elif ref_scope == REF_SCOPE_ALL_REFS:
        all_refs = True
    else:
        raise ValueError(f"Unsupported ref_scope {ref_scope!r}")

    history_since = _parse_history_datetime(since)
    history_until = _parse_history_datetime(until)
    git_since = None if history_since is not None else since
    git_until = None if history_until is not None else until

    raw_log = read_commit_log(
        mirror,
        since=git_since,
        until=git_until,
        revision=revision,
        all_refs=all_refs,
    )
    commits = _filter_commits_by_authored_at(
        parse_git_log(raw_log, repo=repo_key),
        since=history_since,
        until=history_until,
    )
    return _RepoCrawlResult(repo=repo, commits=commits, ref_sha=current_ref_sha, repo_key=repo_key)


def _parse_history_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _filter_commits_by_authored_at(
    commits: list[CommitRecord],
    *,
    since: datetime | None,
    until: datetime | None,
) -> list[CommitRecord]:
    if since is None and until is None:
        return commits
    return [
        commit
        for commit in commits
        if (since is None or commit.authored_at.astimezone(timezone.utc) >= since)
        and (until is None or commit.authored_at.astimezone(timezone.utc) <= until)
    ]


def _previous_state_matches_scope(
    previous_state: RepoState | None,
    *,
    default_branch: str,
    history_since: str | None,
    history_until: str | None,
) -> bool:
    if previous_state is None:
        return False
    if previous_state.history_since == LEGACY_UNKNOWN_HISTORY_WINDOW:
        return False
    if previous_state.semantics_version != CURRENT_REPO_STATE_SEMANTICS_VERSION:
        return False
    return (
        previous_state.default_branch == default_branch
        and previous_state.history_since == history_since
        and previous_state.history_until == history_until
    )


def _build_repository_rows(*, org: str, run_id: str, repositories: list[RepoInfo]) -> list[RepositoryRow]:
    return [
        RepositoryRow(
            run_id=run_id,
            org=org,
            name=repo.name,
            full_name=repo.full_name,
            clone_url=redact_url_credentials(repo.clone_url),
            ssh_url=redact_url_credentials(repo.ssh_url),
            default_branch=repo.default_branch,
            pushed_at=repo.pushed_at,
            archived=repo.archived,
            fork=repo.fork,
            private=repo.private,
            language=repo.language,
        )
        for repo in repositories
    ]


def _build_excluded_repository_rows(
    *,
    org: str,
    run_id: str,
    exclusions: list[RepositoryExclusion],
) -> list[ExcludedRepositoryRow]:
    return [
        ExcludedRepositoryRow(
            run_id=run_id,
            org=org,
            name=exclusion.repo.name,
            full_name=exclusion.repo.full_name,
            clone_url=redact_url_credentials(exclusion.repo.clone_url),
            ssh_url=redact_url_credentials(exclusion.repo.ssh_url),
            default_branch=exclusion.repo.default_branch,
            pushed_at=exclusion.repo.pushed_at,
            archived=exclusion.repo.archived,
            fork=exclusion.repo.fork,
            private=exclusion.repo.private,
            language=exclusion.repo.language,
            exclusion_reason=exclusion.reason,
        )
        for exclusion in exclusions
    ]


def _run_scoped_rows(run_id: str, rows: list[object]) -> list[dict[str, object]]:
    return [{"run_id": run_id, **asdict(row)} for row in rows]


def _build_repo_state_updates(
    *,
    ref_scope: str,
    repo_results: list[_RepoCrawlResult],
) -> list[RepoStateUpdate]:
    if ref_scope != REF_SCOPE_DEFAULT_BRANCH:
        return []
    return [
        RepoStateUpdate(
            repo=result.repo_key,
            default_branch=result.repo.default_branch,
            last_ref_sha=result.ref_sha,
        )
        for result in repo_results
        if result.ref_sha
    ]


def _persist_repo_state_updates(
    store: CrawlStateStore,
    *,
    org: str,
    run_id: str,
    history_since: str | None,
    history_until: str | None,
    updates: list[RepoStateUpdate],
) -> None:
    for update in updates:
        store.update_repo_state(
            org=org,
            repo=update.repo,
            default_branch=update.default_branch,
            last_ref_sha=update.last_ref_sha,
            run_id=run_id,
            history_since=history_since,
            history_until=history_until,
        )


def finalize_crawl_state(
    result: CrawlResult,
    state_db: str | Path,
    *,
    status: str | None = None,
    error_message: str | None = None,
    update_repo_states: bool = True,
) -> CrawlResult:
    """Persist deferred crawl run status and, when safe, incremental repo heads."""
    store = CrawlStateStore(state_db)
    final_status = status or result.run.status
    final_error = result.run.error_message if error_message is None else error_message
    if update_repo_states:
        _persist_repo_state_updates(
            store,
            org=result.org,
            run_id=result.run.run_id,
            history_since=result.run.history_since,
            history_until=result.run.history_until,
            updates=result.repo_state_updates,
        )
    run = _finish_run(
        store,
        result.run,
        status=final_status,
        repositories_discovered=result.run.repositories_discovered,
        repositories_selected=result.run.repositories_selected,
        repositories_crawled=result.run.repositories_crawled,
        repositories_failed=result.run.repositories_failed,
        commits_parsed=result.run.commits_parsed,
        error_message=final_error,
    )
    return replace(result, run=run)


def _start_run(
    store: CrawlStateStore | None,
    *,
    org: str,
    ref_scope: str,
    since: str | None,
    until: str | None,
    active_since: str | None,
) -> CrawlRunRecord:
    if store:
        return store.start_run(
            org=org,
            ref_scope=ref_scope,
            history_since=since,
            history_until=until,
            active_since=active_since,
        )
    return CrawlRunRecord(
        run_id=str(uuid.uuid4()),
        org=org,
        started_at=utc_now(),
        finished_at=None,
        status="running",
        ref_scope=ref_scope,
        history_since=since,
        history_until=until,
        active_since=active_since,
        repositories_discovered=0,
        repositories_selected=0,
        repositories_crawled=0,
        repositories_failed=0,
        commits_parsed=0,
        error_message=None,
    )


def _finish_run(
    store: CrawlStateStore | None,
    run: CrawlRunRecord,
    *,
    status: str,
    repositories_discovered: int,
    repositories_selected: int,
    repositories_crawled: int,
    repositories_failed: int,
    commits_parsed: int,
    error_message: str | None,
) -> CrawlRunRecord:
    if store:
        return store.finish_run(
            run.run_id,
            status=status,
            repositories_discovered=repositories_discovered,
            repositories_selected=repositories_selected,
            repositories_crawled=repositories_crawled,
            repositories_failed=repositories_failed,
            commits_parsed=commits_parsed,
            error_message=error_message,
        )
    return CrawlRunRecord(
        run_id=run.run_id,
        org=run.org,
        started_at=run.started_at,
        finished_at=utc_now(),
        status=status,
        ref_scope=run.ref_scope,
        history_since=run.history_since,
        history_until=run.history_until,
        active_since=run.active_since,
        repositories_discovered=repositories_discovered,
        repositories_selected=repositories_selected,
        repositories_crawled=repositories_crawled,
        repositories_failed=repositories_failed,
        commits_parsed=commits_parsed,
        error_message=error_message,
    )


def build_crawl_summary(result: CrawlResult) -> dict[str, object]:
    """Build a compact human/reporting summary from structured crawl rows."""
    excluded_by_reason = Counter(row.exclusion_reason for row in result.excluded_repositories)
    path_class_totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"files_changed": 0, "lines_added": 0, "lines_deleted": 0}
    )
    repo_totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"commits": 0, "files_changed": 0, "lines_added": 0, "lines_deleted": 0}
    )
    path_totals: dict[tuple[str, str, str], dict[str, int]] = defaultdict(
        lambda: {"files_changed": 0, "lines_added": 0, "lines_deleted": 0}
    )

    for commit in result.raw_commits:
        repo_bucket = repo_totals[commit.repo]
        repo_bucket["commits"] += 1
        repo_bucket["files_changed"] += commit.files_changed
        repo_bucket["lines_added"] += commit.lines_added
        repo_bucket["lines_deleted"] += commit.lines_deleted

    for change in result.file_changes:
        path_class_bucket = path_class_totals[change.path_class]
        path_class_bucket["files_changed"] += 1
        path_class_bucket["lines_added"] += change.additions
        path_class_bucket["lines_deleted"] += change.deletions

        path_bucket = path_totals[(change.repo, change.path, change.path_class)]
        path_bucket["files_changed"] += 1
        path_bucket["lines_added"] += change.additions
        path_bucket["lines_deleted"] += change.deletions

    generated_like = [change for change in result.file_changes if change.is_generated_like]
    source_like = [change for change in result.file_changes if not change.is_generated_like]
    first_day = result.aggregates.org_days[0].date if result.aggregates.org_days else None
    last_day = result.aggregates.org_days[-1].date if result.aggregates.org_days else None
    totals = {
        "commits": len(result.raw_commits),
        "file_changes": len(result.file_changes),
        "lines_added": sum(row.lines_added for row in result.raw_commits),
        "lines_deleted": sum(row.lines_deleted for row in result.raw_commits),
        "active_days": len(result.aggregates.org_days),
        "repo_days": len(result.aggregates.repo_days),
        "contributor_days": len(result.aggregates.contributor_days),
        "distinct_contributor_keys": _distinct_contributor_keys(result.raw_commits),
        "first_day": first_day,
        "last_day": last_day,
    }
    calendar_span = _calendar_span(first_day, last_day)

    return {
        "run_id": result.run.run_id,
        "org": result.org,
        "status": result.run.status,
        "ref_scope": result.run.ref_scope,
        "history_since": result.run.history_since,
        "history_until": result.run.history_until,
        "active_since": result.run.active_since,
        "repositories": {
            "discovered": result.run.repositories_discovered,
            "selected": result.run.repositories_selected,
            "crawled": result.run.repositories_crawled,
            "failed": result.run.repositories_failed,
            "excluded": len(result.excluded_repositories),
            "excluded_by_reason": dict(sorted(excluded_by_reason.items())),
        },
        "totals": totals,
        "calendar_span": calendar_span,
        "averages": _calendar_average_rates(totals, calendar_span),
        "source_like_totals": {
            "file_changes": len(source_like),
            "lines_added": sum(row.additions for row in source_like),
            "lines_deleted": sum(row.deletions for row in source_like),
        },
        "generated_like_totals": {
            "file_changes": len(generated_like),
            "lines_added": sum(row.additions for row in generated_like),
            "lines_deleted": sum(row.deletions for row in generated_like),
        },
        "path_classes": dict(sorted(path_class_totals.items())),
        "top_repositories_by_commits": _top_repo_summaries(repo_totals),
        "top_paths_by_lines_added": _top_path_summaries(path_totals),
        "caveats": [
            "Default crawl scope is public, non-fork, non-archived repositories on the default branch unless flags override it.",
            "Line counts are raw git churn from git log --numstat, not current source LOC.",
            "Generated-like totals include lockfiles, generated/vendor files, and specs that can dominate churn.",
        ],
    }


def _distinct_contributor_keys(commits: list[CommitRow]) -> int:
    keys = set()
    for commit in commits:
        if commit.author_login:
            keys.add(f"login:{commit.author_login.strip().lower()}")
        elif commit.author_email:
            keys.add(f"email:{commit.author_email.strip().lower()}")
        else:
            keys.add(f"name:{commit.author_name.strip()}")
    return len(keys)


def _calendar_span(first_day: str | None, last_day: str | None) -> dict[str, int]:
    if first_day is None or last_day is None:
        return {"days": 0, "weeks": 0, "months": 0}

    start = date.fromisoformat(first_day)
    end = date.fromisoformat(last_day)
    days = (end - start).days + 1
    start_week = start - timedelta(days=start.weekday())
    end_week = end - timedelta(days=end.weekday())
    weeks = ((end_week - start_week).days // 7) + 1
    months = ((end.year - start.year) * 12) + end.month - start.month + 1
    return {"days": days, "weeks": weeks, "months": months}


def _calendar_average_rates(
    totals: dict[str, object],
    calendar_span: dict[str, int],
) -> dict[str, dict[str, float]]:
    metrics = ("commits", "file_changes", "lines_added", "lines_deleted")

    def rates_for(denominator: int) -> dict[str, float]:
        if denominator <= 0:
            return {metric: 0.0 for metric in metrics}
        return {metric: round(float(totals[metric]) / denominator, 2) for metric in metrics}

    return {
        "per_calendar_day": rates_for(calendar_span["days"]),
        "per_calendar_week": rates_for(calendar_span["weeks"]),
        "per_calendar_month": rates_for(calendar_span["months"]),
    }


def _top_repo_summaries(repo_totals: dict[str, dict[str, int]], *, limit: int = 10) -> list[dict[str, object]]:
    rows = [
        {"repo": repo, **totals}
        for repo, totals in sorted(
            repo_totals.items(),
            key=lambda item: (-item[1]["commits"], item[0]),
        )
    ]
    return rows[:limit]


def _top_path_summaries(
    path_totals: dict[tuple[str, str, str], dict[str, int]],
    *,
    limit: int = 10,
) -> list[dict[str, object]]:
    rows = [
        {"repo": repo, "path": path, "path_class": path_class, **totals}
        for (repo, path, path_class), totals in sorted(
            path_totals.items(),
            key=lambda item: (-item[1]["lines_added"], item[0][0], item[0][1]),
        )
    ]
    return rows[:limit]


def _format_calendar_average(label: str, rates: dict[str, float]) -> str:
    return (
        f"- {label}: {rates['commits']} commits, {rates['file_changes']} file changes, "
        f"+{rates['lines_added']} / -{rates['lines_deleted']} lines"
    )


def _render_summary_markdown(summary: dict[str, object]) -> str:
    repositories = summary["repositories"]
    totals = summary["totals"]
    calendar_span = summary["calendar_span"]
    averages = summary["averages"]
    source_like = summary["source_like_totals"]
    generated_like = summary["generated_like_totals"]
    lines = [
        f"# git-crawl summary for {summary['org']}",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Status: **{summary['status']}**",
        f"- Ref scope: `{summary['ref_scope']}`",
        f"- Repositories discovered: {repositories['discovered']}",
        f"- Repositories selected: {repositories['selected']}",
        f"- Repositories excluded: {repositories['excluded']}",
        f"- Repository failures: {repositories['failed']}",
        f"- Commits: {totals['commits']}",
        f"- File-change rows: {totals['file_changes']}",
        f"- Lines added: {totals['lines_added']}",
        f"- Lines deleted: {totals['lines_deleted']}",
        f"- Active days: {totals['active_days']} ({totals['first_day']} to {totals['last_day']})",
        f"- Calendar span: {calendar_span['days']} days, {calendar_span['weeks']} weeks, {calendar_span['months']} months",
        "",
        "## Interpretation",
        "",
        "These totals are raw git churn from `git log --numstat`, not current source LOC.",
        f"- Source-like additions: {source_like['lines_added']}",
        f"- Generated-like additions: {generated_like['lines_added']}",
        "",
        "## Calendar averages",
        "",
        _format_calendar_average("Per calendar day", averages["per_calendar_day"]),
        _format_calendar_average("Per calendar week", averages["per_calendar_week"]),
        _format_calendar_average("Per calendar month", averages["per_calendar_month"]),
        "",
        "## Top repos by commits",
        "",
    ]
    for row in summary["top_repositories_by_commits"]:
        lines.append(
            f"- **{row['repo']}**: {row['commits']} commits, "
            f"+{row['lines_added']} / -{row['lines_deleted']} lines"
        )
    lines.extend(["", "## Top paths by additions", ""])
    for row in summary["top_paths_by_lines_added"]:
        lines.append(
            f"- **{row['repo']}** `{row['path']}` ({row['path_class']}): "
            f"+{row['lines_added']} / -{row['lines_deleted']} lines"
        )
    lines.extend(["", "## Caveats", ""])
    for caveat in summary["caveats"]:
        lines.append(f"- {caveat}")
    lines.append("")
    return "\n".join(lines)


def write_crawl_outputs(
    result: CrawlResult,
    output_dir: str | Path,
    *,
    write_json: bool = True,
    write_csv_files: bool = True,
) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    repository_rows = _build_repository_rows(
        org=result.org,
        run_id=result.run.run_id,
        repositories=result.repositories,
    )
    org_day_rows = _run_scoped_rows(result.run.run_id, result.aggregates.org_days)
    repo_day_rows = _run_scoped_rows(result.run.run_id, result.aggregates.repo_days)
    contributor_day_rows = _run_scoped_rows(result.run.run_id, result.aggregates.contributor_days)

    if write_json:
        crawl_run_jsonl = output_dir / "crawl_runs.jsonl"
        org_jsonl = output_dir / "org_days.jsonl"
        repo_jsonl = output_dir / "repo_days.jsonl"
        contributor_jsonl = output_dir / "contributor_days.jsonl"
        repository_jsonl = output_dir / "repositories.jsonl"
        excluded_jsonl = output_dir / "excluded_repositories.jsonl"
        commits_jsonl = output_dir / "commits.jsonl"
        file_changes_jsonl = output_dir / "file_changes.jsonl"
        failures_jsonl = output_dir / "repo_failures.jsonl"
        summary_json = output_dir / "summary.json"
        summary_md = output_dir / "summary.md"
        write_jsonl(crawl_run_jsonl, [result.run])
        write_jsonl(org_jsonl, org_day_rows)
        write_jsonl(repo_jsonl, repo_day_rows)
        write_jsonl(contributor_jsonl, contributor_day_rows)
        write_jsonl(repository_jsonl, repository_rows)
        write_jsonl(excluded_jsonl, result.excluded_repositories)
        write_jsonl(commits_jsonl, result.raw_commits)
        write_jsonl(file_changes_jsonl, result.file_changes)
        write_jsonl(failures_jsonl, result.failed_repositories)
        summary = build_crawl_summary(result)
        summary_json.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        summary_md.write_text(_render_summary_markdown(summary), encoding="utf-8")
        written.extend(
            [
                crawl_run_jsonl,
                org_jsonl,
                repo_jsonl,
                contributor_jsonl,
                repository_jsonl,
                excluded_jsonl,
                commits_jsonl,
                file_changes_jsonl,
                failures_jsonl,
                summary_json,
                summary_md,
            ]
        )

    if write_csv_files:
        crawl_run_csv = output_dir / "crawl_runs.csv"
        org_csv = output_dir / "org_days.csv"
        repo_csv = output_dir / "repo_days.csv"
        contributor_csv = output_dir / "contributor_days.csv"
        repository_csv = output_dir / "repositories.csv"
        excluded_csv = output_dir / "excluded_repositories.csv"
        commits_csv = output_dir / "commits.csv"
        file_changes_csv = output_dir / "file_changes.csv"
        failures_csv = output_dir / "repo_failures.csv"
        write_csv(crawl_run_csv, [result.run], fieldnames=CRAWL_RUN_FIELDS)
        write_csv(org_csv, org_day_rows, fieldnames=ORG_DAY_FIELDS)
        write_csv(repo_csv, repo_day_rows, fieldnames=REPO_DAY_FIELDS)
        write_csv(
            contributor_csv,
            contributor_day_rows,
            fieldnames=CONTRIBUTOR_DAY_FIELDS,
        )
        write_csv(repository_csv, repository_rows, fieldnames=REPOSITORY_FIELDS)
        write_csv(excluded_csv, result.excluded_repositories, fieldnames=EXCLUDED_REPOSITORY_FIELDS)
        write_csv(commits_csv, result.raw_commits, fieldnames=COMMIT_FIELDS)
        write_csv(file_changes_csv, result.file_changes, fieldnames=FILE_CHANGE_FIELDS)
        write_csv(failures_csv, result.failed_repositories, fieldnames=REPO_FAILURE_FIELDS)
        written.extend(
            [
                crawl_run_csv,
                org_csv,
                repo_csv,
                contributor_csv,
                repository_csv,
                excluded_csv,
                commits_csv,
                file_changes_csv,
                failures_csv,
            ]
        )

    return written
