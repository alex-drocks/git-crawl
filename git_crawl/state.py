from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

LEGACY_UNKNOWN_HISTORY_WINDOW = "__git_crawl_legacy_unknown_history_window__"
CURRENT_REPO_STATE_SEMANTICS_VERSION = "repo-state-semantics-v2"


@dataclass(frozen=True)
class CrawlRunRecord:
    run_id: str
    org: str
    started_at: str
    finished_at: str | None
    status: str
    ref_scope: str
    history_since: str | None
    history_until: str | None
    active_since: str | None
    repositories_discovered: int
    repositories_selected: int
    repositories_crawled: int
    repositories_failed: int
    commits_parsed: int
    error_message: str | None


@dataclass(frozen=True)
class RepoState:
    org: str
    repo: str
    default_branch: str
    last_ref_sha: str
    history_since: str | None
    history_until: str | None
    semantics_version: str | None
    last_successful_run_id: str
    last_crawled_at: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class CrawlStateStore:
    """SQLite-backed crawl state for run metadata and incremental repo heads."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("pragma journal_mode=wal")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                create table if not exists crawl_runs (
                    run_id text primary key,
                    org text not null,
                    started_at text not null,
                    finished_at text,
                    status text not null,
                    ref_scope text not null,
                    history_since text,
                    history_until text,
                    active_since text,
                    repositories_discovered integer not null default 0,
                    repositories_selected integer not null default 0,
                    repositories_crawled integer not null default 0,
                    repositories_failed integer not null default 0,
                    commits_parsed integer not null default 0,
                    error_message text
                )
                """
            )
            connection.execute(
                """
                create table if not exists repo_states (
                    org text not null,
                    repo text not null,
                    default_branch text not null,
                    last_ref_sha text not null,
                    history_since text,
                    history_until text,
                    semantics_version text,
                    last_successful_run_id text not null,
                    last_crawled_at text not null,
                    primary key (org, repo)
                )
                """
            )
            _ensure_repo_state_columns(connection)

    def start_run(
        self,
        *,
        org: str,
        ref_scope: str,
        history_since: str | None,
        history_until: str | None,
        active_since: str | None,
    ) -> CrawlRunRecord:
        run = CrawlRunRecord(
            run_id=str(uuid.uuid4()),
            org=org,
            started_at=utc_now(),
            finished_at=None,
            status="running",
            ref_scope=ref_scope,
            history_since=history_since,
            history_until=history_until,
            active_since=active_since,
            repositories_discovered=0,
            repositories_selected=0,
            repositories_crawled=0,
            repositories_failed=0,
            commits_parsed=0,
            error_message=None,
        )
        with self._connect() as connection:
            connection.execute(
                """
                insert into crawl_runs (
                    run_id, org, started_at, finished_at, status, ref_scope,
                    history_since, history_until, active_since,
                    repositories_discovered, repositories_selected,
                    repositories_crawled, repositories_failed, commits_parsed,
                    error_message
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.org,
                    run.started_at,
                    run.finished_at,
                    run.status,
                    run.ref_scope,
                    run.history_since,
                    run.history_until,
                    run.active_since,
                    run.repositories_discovered,
                    run.repositories_selected,
                    run.repositories_crawled,
                    run.repositories_failed,
                    run.commits_parsed,
                    run.error_message,
                ),
            )
        return run

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        repositories_discovered: int,
        repositories_selected: int,
        repositories_crawled: int,
        repositories_failed: int,
        commits_parsed: int,
        error_message: str | None,
    ) -> CrawlRunRecord:
        finished_at = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                update crawl_runs
                   set finished_at = ?, status = ?,
                       repositories_discovered = ?, repositories_selected = ?,
                       repositories_crawled = ?, repositories_failed = ?,
                       commits_parsed = ?, error_message = ?
                 where run_id = ?
                """,
                (
                    finished_at,
                    status,
                    repositories_discovered,
                    repositories_selected,
                    repositories_crawled,
                    repositories_failed,
                    commits_parsed,
                    error_message,
                    run_id,
                ),
            )
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(f"Unknown crawl run {run_id}")
        return run

    def get_run(self, run_id: str) -> CrawlRunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                select run_id, org, started_at, finished_at, status, ref_scope,
                       history_since, history_until, active_since,
                       repositories_discovered, repositories_selected,
                       repositories_crawled, repositories_failed, commits_parsed,
                       error_message
                  from crawl_runs
                 where run_id = ?
                """,
                (run_id,),
            ).fetchone()
        return _crawl_run_from_row(row) if row else None

    def get_repo_state(self, *, org: str, repo: str) -> RepoState | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                select org, repo, default_branch, last_ref_sha,
                       history_since, history_until, semantics_version,
                       last_successful_run_id, last_crawled_at
                  from repo_states
                 where org = ? and repo = ?
                """,
                (org, repo),
            ).fetchone()
        return _repo_state_from_row(row) if row else None

    def update_repo_state(
        self,
        *,
        org: str,
        repo: str,
        default_branch: str,
        last_ref_sha: str,
        run_id: str,
        history_since: str | None = None,
        history_until: str | None = None,
        semantics_version: str = CURRENT_REPO_STATE_SEMANTICS_VERSION,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                insert into repo_states (
                    org, repo, default_branch, last_ref_sha, history_since, history_until,
                    semantics_version, last_successful_run_id, last_crawled_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(org, repo) do update set
                    default_branch = excluded.default_branch,
                    last_ref_sha = excluded.last_ref_sha,
                    history_since = excluded.history_since,
                    history_until = excluded.history_until,
                    semantics_version = excluded.semantics_version,
                    last_successful_run_id = excluded.last_successful_run_id,
                    last_crawled_at = excluded.last_crawled_at
                """,
                (
                    org,
                    repo,
                    default_branch,
                    last_ref_sha,
                    history_since,
                    history_until,
                    semantics_version,
                    run_id,
                    utc_now(),
                ),
            )


def _ensure_repo_state_columns(connection: sqlite3.Connection) -> None:
    existing = {
        str(row[1])
        for row in connection.execute("pragma table_info(repo_states)").fetchall()
    }
    missing_history_columns = "history_since" not in existing or "history_until" not in existing
    if "history_since" not in existing:
        connection.execute("alter table repo_states add column history_since text")
    if "history_until" not in existing:
        connection.execute("alter table repo_states add column history_until text")
    if "semantics_version" not in existing:
        connection.execute("alter table repo_states add column semantics_version text")
    if missing_history_columns:
        connection.execute(
            """
            update repo_states
               set history_since = ?, history_until = null
            """,
            (LEGACY_UNKNOWN_HISTORY_WINDOW,),
        )


def _crawl_run_from_row(row: tuple[object, ...]) -> CrawlRunRecord:
    return CrawlRunRecord(
        run_id=str(row[0]),
        org=str(row[1]),
        started_at=str(row[2]),
        finished_at=str(row[3]) if row[3] is not None else None,
        status=str(row[4]),
        ref_scope=str(row[5]),
        history_since=str(row[6]) if row[6] is not None else None,
        history_until=str(row[7]) if row[7] is not None else None,
        active_since=str(row[8]) if row[8] is not None else None,
        repositories_discovered=int(row[9]),
        repositories_selected=int(row[10]),
        repositories_crawled=int(row[11]),
        repositories_failed=int(row[12]),
        commits_parsed=int(row[13]),
        error_message=str(row[14]) if row[14] is not None else None,
    )


def _repo_state_from_row(row: tuple[object, ...]) -> RepoState:
    return RepoState(
        org=str(row[0]),
        repo=str(row[1]),
        default_branch=str(row[2]),
        last_ref_sha=str(row[3]),
        history_since=str(row[4]) if row[4] is not None else None,
        history_until=str(row[5]) if row[5] is not None else None,
        semantics_version=str(row[6]) if row[6] is not None else None,
        last_successful_run_id=str(row[7]),
        last_crawled_at=str(row[8]),
    )
