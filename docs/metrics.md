# Git Crawl Metric Definitions

Git Crawl emits raw rows plus derived daily aggregates. Metric definitions are intentionally explicit so downstream jobs can recompute or compare results safely.

## Crawl scope

- Repositories can be discovered from the GitHub organization repositories API (`crawl-org`) or resolved from an explicit URL manifest (`crawl-repos`). Discovery/resolution uses a stable full-name ordering, de-duplicates repositories by `full_name`, then selected repositories are ordered by `pushed_at` descending with `full_name` as the deterministic tie-breaker.
- By default, private repositories are excluded from tracking. The API request defaults to `type=public`, and any private repositories returned by an authenticated request are filtered out before crawling.
- Archived repositories are excluded unless `include_archived` is enabled.
- Fork repositories are excluded unless `include_forks` is enabled.
- The default ref scope is the repository default branch. Use `ref_scope = "all-refs"` only when you intentionally want branches/tags beyond the active default branch.
- Dates in aggregate tables are UTC dates derived from Git author timestamps.
- Parallel repository crawls are normalized back to selected repository order before raw rows are written, so output row ordering is deterministic for the same selected repositories and Git history.

## Raw commits

One raw commits row represents one parsed Git commit included by the crawl's ref scope and history window.

Fields:

- `run_id`: crawl run identifier.
- `org`: crawl target label. For `crawl-org`, this is the GitHub organization login; for `crawl-repos`, this is the manifest `target` or CLI `--target` value.
- `repo`: repository identity. For `crawl-org`, this is the short repository name within the org; for `crawl-repos`, this is the full `owner/repo` name to avoid cross-owner collisions.
- `sha`: commit SHA.
- `parents`: space-separated parent SHAs.
- `parent_count`: number of parent commits.
- `is_merge_commit`: true when `parent_count > 1`.
- `author_name`: Git author name.
- `author_email`: Git author email.
- `author_login`: GitHub login parsed from public noreply email formats when available.
- `authored_at`: Git author timestamp as an ISO-8601 string.
- `files_changed`: count of raw file changes attached to the commit.
- `lines_added`: sum of text additions from Git numstat rows.
- `lines_deleted`: sum of text deletions from Git numstat rows.

## File changes

One file changes row represents one `git log --numstat` file row for an included commit.

Fields:

- `run_id`: crawl run identifier.
- `org`: crawl target label. For `crawl-org`, this is the GitHub organization login; for `crawl-repos`, this is the manifest `target` or CLI `--target` value.
- `repo`: repository identity. For `crawl-org`, this is the short repository name within the org; for `crawl-repos`, this is the full `owner/repo` name to avoid cross-owner collisions.
- `sha`: commit SHA.
- `path`: changed path as emitted by Git numstat.
- `additions`: text lines added. Binary file changes use `0` because Git emits `-` for numstat counts.
- `deletions`: text lines deleted. Binary file changes use `0` because Git emits `-` for numstat counts.
- `is_binary`: true when Git emitted binary numstat markers.
- `path_class`: broad interpretation bucket: `source`, `lockfile`, `generated`, `spec`, `docs`, `binary`, `vendored`, or `unknown`.
- `is_generated_like`: true for classes that commonly inflate churn (`lockfile`, `generated`, `spec`, and `vendored`). Raw counts are unchanged.
- `is_lockfile`: true when the changed path is recognized as a dependency lockfile.

## Repository metadata

One `repositories` row represents one selected repository for one crawl run.

Fields:

- `run_id`: crawl run identifier.
- `org`: crawl target label. For `crawl-org`, this is the GitHub organization login; for `crawl-repos`, this is the manifest `target` or CLI `--target` value.
- `name`: short repository name.
- `full_name`: GitHub `owner/name` repository identifier.
- `clone_url`: HTTPS clone URL from GitHub.
- `ssh_url`: SSH clone URL from GitHub.
- `default_branch`: repository default branch reported by GitHub.
- `pushed_at`: GitHub repository push timestamp, when available.
- `archived`: true when the repository is archived.
- `fork`: true when the repository is a fork.
- `private`: true when GitHub reports the repository as private; private repositories are filtered before crawling.
- `language`: primary language reported by GitHub, when available.

## Excluded repositories

One `excluded_repositories` row represents one discovered repository that was not selected for the crawl. It uses the same repository metadata fields as `repositories`, plus:

- `exclusion_reason`: one of `private`, `archived`, `fork`, `inactive_before_active_since`, or `over_max_repos`.

This table lets dashboards reconcile GitHub's discovered repository count with the number of repositories actually crawled.

## Target-day aggregates

The file is still named `org_days` for schema compatibility. One `org_days` row represents the whole crawl target on one UTC date, across all selected repositories included in the run. For `crawl-org`, the target is an organization/owner; for `crawl-repos`, it is the manifest or CLI target label.

Fields:

- `run_id`: crawl run identifier.
- `org`: crawl target label. For `crawl-org`, this is the GitHub organization login; for `crawl-repos`, this is the manifest `target` or CLI `--target` value.
- `date`: UTC date derived from Git author timestamps.
- `commits`: count of unique `(repo, commit SHA)` pairs included for that target/date.
- `unique_contributors`: count of distinct contributor identities across all selected repositories for that target/date. Identity is normalized `author_login` when available, else lower-cased `author_email`, else `author_name`; contributors active in multiple repositories on the same UTC date are counted once.
- `lines_added`: sum of file-change additions for included commits on that UTC date across all selected repositories.
- `lines_deleted`: sum of file-change deletions for included commits on that UTC date across all selected repositories.
- `files_changed`: count of file-change rows for included commits on that UTC date across all selected repositories.

## Repo-day aggregates

One `repo_days` row represents one repository on one UTC date.

Fields:

- `run_id`: crawl run identifier.
- `org`: crawl target label. For `crawl-org`, this is the GitHub organization login; for `crawl-repos`, this is the manifest `target` or CLI `--target` value.
- `repo`: repository identity. For `crawl-org`, this is the short repository name within the org; for `crawl-repos`, this is the full `owner/repo` name to avoid cross-owner collisions.
- `date`: UTC date derived from Git author timestamps.
- `commits`: count of unique commit SHAs included for that repo/date.
- `unique_contributors`: count of distinct contributor identities for that repo/date. Identity is normalized `author_login` when available, else lower-cased `author_email`, else `author_name`.
- `lines_added`: sum of file-change additions for included commits on that UTC date.
- `lines_deleted`: sum of file-change deletions for included commits on that UTC date.
- `files_changed`: count of file-change rows for included commits on that UTC date.

## Contributor-day aggregates

One `contributor_days` row represents one repository, one UTC date, and one
contributor identity. Identity is normalized `author_login` when available, else
lower-cased `author_email`, else `author_name`.

Fields:

- `run_id`: crawl run identifier.
- `org`: crawl target label. For `crawl-org`, this is the GitHub organization login; for `crawl-repos`, this is the manifest `target` or CLI `--target` value.
- `repo`: repository identity. For `crawl-org`, this is the short repository name within the org; for `crawl-repos`, this is the full `owner/repo` name to avoid cross-owner collisions.
- `date`: UTC date derived from Git author timestamps.
- `author_name`: Git author name for this contributor bucket.
- `author_email`: normalized lower-case Git author email retained for lineage; the bucket key falls
  back to `author_name` when both `author_login` and `author_email` are missing.
- `author_login`: normalized GitHub login parsed from public noreply email formats when available.
- `commits`: count of unique commit SHAs for that contributor identity on that repo/date.
- `lines_added`: sum of file-change additions for that contributor identity on that repo/date.
- `lines_deleted`: sum of file-change deletions for that contributor identity on that repo/date.
- `files_changed`: count of file-change rows for that contributor identity on that repo/date.

## Incremental crawling

When a SQLite state database is configured and `ref_scope = "default-branch"`, Git Crawl stores the last successfully crawled default branch SHA per repository and history window. On the next successful run with the same default branch, `--since`, and `--until` values, it reads the Git range `previous_sha..current_sha` instead of the full default branch history. If the branch or history window changes, or if the previous SHA is missing from the mirror after a cache rebuild or force-push, the crawler falls back to a full read of the current default branch scope. State databases created before history-window tracking are treated as unknown provenance and get one full read before new incremental state is trusted. In CLI runs, repository state is advanced only after output files are written successfully; output failures mark the run failed without updating repository SHAs.

Incremental outputs are run-scoped: rows emitted in a run describe the commits processed during that run, not a full historical replacement table. Downstream consumers should use `run_id` and the raw commits/file changes tables for lineage and deduplication. If a run has `status = "partial"` or `status = "failed"`, `org_days`, `repo_days`, and `contributor_days` include only successfully crawled repositories; dashboards should join `crawl_runs` and `repo_failures` before treating org-level metrics as complete.

## Summary reports

When JSON output is enabled, Git Crawl also writes:

- `summary.json`: totals, source-like versus generated-like churn, calendar-span averages, path-class breakdowns, top repositories, top paths by additions, exclusion counts, and interpretation caveats.
- `summary.md`: the same core facts in a human-readable report.

Calendar averages are computed from total commits, file changes, lines added, and
lines deleted divided by the inclusive calendar span from `first_day` to
`last_day`. The `calendar_span` block reports the denominator counts:

- `days`: inclusive calendar days.
- `weeks`: Monday-start calendar weeks touched by the inclusive date range.
- `months`: calendar months touched by the inclusive date range.

These are calendar-span averages, not active-period averages; inactive days,
weeks, and months inside the first/last activity range are included in the
denominator.

The summary is intentionally derived from the structured row files, so downstream jobs can recompute it if they need custom path filters or different top-N logic.
