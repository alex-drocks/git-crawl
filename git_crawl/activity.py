from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import replace

from .gitlog import CommitRecord, FileChange
from .metrics import aggregate_daily, contributor_identity_key
from .path_classification import (
    PATH_CLASS_BINARY,
    PATH_CLASS_GENERATED,
    PATH_CLASS_LOCKFILE,
    PATH_CLASS_SPEC,
    PATH_CLASS_VENDORED,
    classify_path,
)

ACTIVITY_SCHEMA_VERSION = "git-crawl-activity-v1"
ACTIVITY_FILTER_MODE = "source_like"
ACTIVITY_EXCLUDED_REASONS = [
    "binary",
    "lockfile",
    "generated",
    "vendored",
    "spec/schema-like",
]

_EXCLUSION_REASON_BY_PATH_CLASS = {
    PATH_CLASS_BINARY: "binary",
    PATH_CLASS_LOCKFILE: "lockfile",
    PATH_CLASS_GENERATED: "generated",
    PATH_CLASS_VENDORED: "vendored",
    PATH_CLASS_SPEC: "spec/schema-like",
}


def build_activity(
    *,
    org: str,
    run_id: str,
    status: str,
    ref_scope: str,
    history_since: str | None,
    history_until: str | None,
    commits: Iterable[CommitRecord],
) -> dict[str, object]:
    """Build the canonical credited activity contract for a crawl run."""
    source_commits = list(commits)
    credited_commits = _credited_activity_commits(source_commits)
    aggregates = aggregate_daily(org, credited_commits)
    active_days = len(aggregates.org_days)
    totals = {
        "commits": len(credited_commits),
        "file_changes": sum(len(commit.changes) for commit in credited_commits),
        "lines_added": sum(change.additions for commit in credited_commits for change in commit.changes),
        "lines_deleted": sum(change.deletions for commit in credited_commits for change in commit.changes),
        "active_days": active_days,
        "repo_days": len(aggregates.repo_days),
        "contributor_days": len(aggregates.contributor_days),
        "distinct_contributors": len({contributor_identity_key(commit) for commit in credited_commits}),
    }

    return {
        "schema_version": ACTIVITY_SCHEMA_VERSION,
        "run_id": run_id,
        "org": org,
        "status": status,
        "ref_scope": ref_scope,
        "history_since": history_since,
        "history_until": history_until,
        "filter": {
            "mode": ACTIVITY_FILTER_MODE,
            "excluded_reasons": ACTIVITY_EXCLUDED_REASONS,
        },
        "totals": totals,
        "averages": {
            "per_active_day": _average_rates(totals, active_days),
        },
        "skipped": _skipped_totals(source_commits),
    }


def _credited_activity_commits(commits: Iterable[CommitRecord]) -> list[CommitRecord]:
    credited: list[CommitRecord] = []
    for commit in commits:
        credited_changes = [change for change in commit.changes if _exclusion_reason(change) is None]
        if credited_changes:
            credited.append(replace(commit, changes=credited_changes))
    return credited


def _skipped_totals(commits: Iterable[CommitRecord]) -> dict[str, object]:
    by_reason: dict[str, dict[str, int]] = defaultdict(_empty_churn_totals)
    skipped = _empty_churn_totals()
    for commit in commits:
        for change in commit.changes:
            reason = _exclusion_reason(change)
            if reason is None:
                continue
            _add_change_totals(skipped, change)
            _add_change_totals(by_reason[reason], change)

    return {
        **skipped,
        "by_reason": {reason: by_reason[reason] for reason in ACTIVITY_EXCLUDED_REASONS if reason in by_reason},
    }


def _exclusion_reason(change: FileChange) -> str | None:
    classification = classify_path(change.path, is_binary=change.is_binary)
    return _EXCLUSION_REASON_BY_PATH_CLASS.get(classification.path_class)


def _empty_churn_totals() -> dict[str, int]:
    return {"file_changes": 0, "lines_added": 0, "lines_deleted": 0}


def _add_change_totals(totals: dict[str, int], change: FileChange) -> None:
    totals["file_changes"] += 1
    totals["lines_added"] += change.additions
    totals["lines_deleted"] += change.deletions


def _average_rates(totals: dict[str, object], denominator: int) -> dict[str, float]:
    metrics = ("commits", "file_changes", "lines_added", "lines_deleted")
    if denominator <= 0:
        return {metric: 0.0 for metric in metrics}
    return {metric: round(float(totals[metric]) / denominator, 2) for metric in metrics}
