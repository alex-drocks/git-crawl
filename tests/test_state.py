import sqlite3

from git_crawl.state import CrawlStateStore


def test_sqlite_state_records_crawl_runs_and_repo_heads(tmp_path):
    db_path = tmp_path / "state.sqlite"
    store = CrawlStateStore(db_path)

    run = store.start_run(
        org="chutesai",
        ref_scope="default-branch",
        history_since="2026-01-01",
        history_until=None,
        active_since="2025-01-01T00:00:00Z",
    )
    store.update_repo_state(
        org="chutesai",
        repo="api",
        default_branch="main",
        last_ref_sha="abc123",
        run_id=run.run_id,
        history_since="2026-01-01",
        history_until=None,
    )
    final = store.finish_run(
        run.run_id,
        status="success",
        repositories_discovered=2,
        repositories_selected=1,
        repositories_crawled=1,
        repositories_failed=0,
        commits_parsed=3,
        error_message=None,
    )

    repo_state = store.get_repo_state(org="chutesai", repo="api")
    assert repo_state is not None
    assert repo_state.default_branch == "main"
    assert repo_state.last_ref_sha == "abc123"
    assert repo_state.history_since == "2026-01-01"
    assert repo_state.history_until is None
    assert repo_state.last_successful_run_id == run.run_id
    assert final.finished_at is not None
    assert final.repositories_discovered == 2
    assert final.commits_parsed == 3

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "select org, status, ref_scope, repositories_selected, commits_parsed from crawl_runs"
        ).fetchall()
    assert rows == [("chutesai", "success", "default-branch", 1, 3)]
