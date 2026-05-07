# Git Crawl

`git-crawl` is a dependency-light Python library and CLI for crawling public GitHub repositories, keeping local bare Git mirrors, extracting exact `git log --numstat` history, and writing structured raw rows plus daily contribution metrics.

It is designed to be **zero-hosting by default**:

- no required hosted API;
- no central scheduled crawler that Alex has to operate;
- users bring their own GitHub token, storage, cache, schedule, and deployment;
- outputs are local JSONL/CSV/JSON/Markdown files that any downstream consumer can load.

## Why clone/fetch repos instead of only using the GitHub API?

GitHub's repository commits list endpoint does not include line additions and deletions. Fetching those values through the REST API requires one extra API call per commit. `git-crawl` uses bare Git mirrors and `git log --numstat` instead, which is more accurate for full history and avoids burning API quota on per-commit line stats.

The GitHub API is still used for public repository discovery and metadata.

## Crawl modes

- `crawl-org`: discover and crawl selected repositories from one GitHub organization, preserving legacy short repo names in raw rows and state.
- `crawl-owner`: discover and crawl selected repositories from a GitHub owner root. It tries organization discovery first, falls back to user discovery when the org does not exist, and uses full `owner/repo` repository identity in raw rows and state. Pass `--target` when the owner is only the discovery source and output rows/state should belong to another target, such as `bittensor-subnet-64`.
- `crawl-repos`: crawl an explicit manifest of GitHub repository URLs. This is the preferred integration point for adapters such as a future `tao-git-crawl`, because exact repo links stay exact and are not expanded into unrelated owner-wide crawls.

## Quick start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'

# Optional but recommended to raise GitHub API rate limits.
export GITHUB_TOKEN='***'

# Crawl one public org, capped to one recent repo for a smoke test.
git-crawl crawl-org chutesai \
  --max-repos 1 \
  --since 2026-01-01 \
  --output-dir out/chutesai-smoke

# Crawl a GitHub owner root that may be an organization or a user.
git-crawl crawl-owner torvalds \
  --owner-type auto \
  --max-repos 1 \
  --since 2026-01-01 \
  --output-dir out/torvalds-smoke

# Crawl an owner, but label output/state as a subnet target.
git-crawl crawl-owner chutesai \
  --target bittensor-subnet-64 \
  --owner-type org \
  --since 2026-01-01 \
  --output-dir out/bittensor-subnet-64
```

## Explicit repository manifests

Use `crawl-repos` when another system has already resolved the repositories to inspect.

`repos.json`:

```json
{
  "target": "bittensor-subnets",
  "repositories": [
    "https://github.com/chutesai/api",
    {"url": "https://github.com/chutesai/worker/tree/main"}
  ]
}
```

Run it:

```bash
git-crawl crawl-repos repos.json \
  --workers 4 \
  --state-db /data/git-crawl/state.sqlite \
  --cache-dir /data/git-crawl/mirrors \
  --output-dir /data/git-crawl/bittensor-subnets/latest
```

Manifest repository URLs are normalized through the GitHub API and de-duplicated by `owner/repo`. Output commit and state rows use full repository names for `crawl-repos`, so two owners can both have a repo named `api` without colliding.

Accepted URL forms include normal HTTPS repo URLs, `.git` clone URLs, SSH clone URLs, and contextual repo URLs such as `/tree/...` or `/blob/...`. Issue and pull-request URLs are rejected because they are not repository crawl targets.

## Output files

`git-crawl` writes run-scoped files. Depending on `--format`, JSONL and/or CSV siblings are emitted.

```text
crawl_runs.jsonl
crawl_runs.csv
repositories.jsonl
repositories.csv
excluded_repositories.jsonl
excluded_repositories.csv
commits.jsonl
commits.csv
file_changes.jsonl
file_changes.csv
org_days.jsonl
org_days.csv
repo_days.jsonl
repo_days.csv
contributor_days.jsonl
contributor_days.csv
repo_failures.jsonl
repo_failures.csv
summary.json
summary.md
output_manifest.json
```

Reports and schema contract:

- `summary.json`: machine-readable run summary, totals, calendar-span averages, path-class breakdowns, top repos, and top paths by lines added. It includes `schema_version` and `output_schema_version` for downstream compatibility checks.
- `summary.md`: human-readable summary with calendar averages and interpretation caveats.
- `output_manifest.json`: versioned output contract listing every dataset, its schema version, emitted filename(s), and ordered fields. Downstream packages should check this file before loading crawl outputs.

Daily aggregate rows:

- `org_days`: target/day totals across all selected repositories, including unique contributors de-duplicated across repositories.
- `repo_days`: repository/day commits, contributors, lines added/deleted, and files changed.
- `contributor_days`: repository/day/contributor-identity commits, lines added/deleted, and files changed.

See [`docs/metrics.md`](docs/metrics.md) for exact definitions, UTC date semantics, default branch scope, binary-file handling, and incremental-crawl behavior.

## Production-oriented example

```bash
git-crawl crawl-org chutesai \
  --active-since 2025-01-01T00:00:00Z \
  --since 2025-01-01 \
  --ref-scope default-branch \
  --workers 4 \
  --state-db /data/git-crawl/state.sqlite \
  --cache-dir /data/git-crawl/mirrors \
  --output-dir /data/git-crawl/chutesai/2026-05-05
```

Defaults:

- Crawls all selected public repositories in the organization; by default that means public non-archived non-fork repos, with an optional `--active-since` cutoff. There is no implicit “main repo only” shortcut. Use `--max-repos` only for smoke tests or intentionally capped samples.
- Excludes archived repos and forks. Add `--include-archived` or `--include-forks` when you intentionally want them. If a config file enables them, `--no-include-archived` or `--no-include-forks` turns them off for one run. Excluded repos are written to `excluded_repositories` with an `exclusion_reason`.
- Crawls only each repository's default branch. Add `--ref-scope all-refs` when you intentionally want all branches/tags.
- `--active-since` accepts an ISO timestamp or date; date-only values are interpreted as midnight UTC.
- Continues past individual repository failures and records them in `repo_failures`. Add `--fail-fast` to stop after the first repository failure and return a failed run with the failure row preserved. Fail-fast crawls run sequentially even if `--workers` is greater than 1, so no already-started background repositories are silently ignored.
- Retries transient GitHub API discovery failures and git mirror clone/fetch failures with bounded jittered exponential backoff. GitHub `Retry-After` and `X-RateLimit-Reset` headers are used before falling back to exponential API retry delays.

## Downstream consumption boundary

`git-crawl` stops at structured data generation. It does not ship a dashboard, hosted API, scheduled crawler, or static-site publisher. Product-specific views, KPI pages, public dashboards, and deployment workflows should live in downstream consumers such as `tao-git-crawl`, private applications, notebooks, BI tools, or a separate reporting package.

## Config file

Use TOML for repeatable organization crawls:

```toml
org = "chutesai"
active_since = "2025-01-01T00:00:00Z"
since = "2026-01-01"
ref_scope = "default-branch"
workers = 4
cache_dir = ".cache/git-crawl"
output_dir = "out/chutesai"
state_db = ".cache/git-crawl/state.sqlite"

[filters]
max_repos = 10
include_archived = false
include_forks = false

[outputs]
format = "all"
```

Run it with:

```bash
git-crawl crawl-org --config crawler.toml
```

Command-line flags override config values when supplied.

## SQLite incremental state

When `--state-db` is set and `--ref-scope default-branch` is used, the crawler records the last successfully crawled default branch SHA per repository and history window. Later runs with the same default branch, `--since`, and `--until` process `previous_sha..current_sha` instead of re-reading the whole branch. If the default branch or history window changes, or if the previous SHA is no longer present in the local mirror after a cache rebuild/force push, the crawler falls back to a full read of the current default branch scope.

For `crawl-org`, state rows use the short repository name within the org target. For `crawl-owner` and `crawl-repos`, state rows use `owner/repo` full names to avoid cross-owner collisions.

The CLI advances repository state after structured output files are written successfully. If output writing fails, the run is marked failed and repository SHAs are not advanced, so a retry can re-emit the missed rows.

Output rows are run-scoped and include `run_id`, so downstream consumers can load new runs incrementally and deduplicate by commit SHA if needed. Repository metadata rows also include `run_id` and `org`/target label, which keeps appended multi-target loads traceable without relying on the output directory name. When a run is `partial` or `failed`, aggregate rows include only successfully crawled repositories; join `crawl_runs` and `repo_failures` before treating aggregates as complete.

## Development

```bash
python -m pip install -e '.[dev]'
python -m ruff check git_crawl tests
python -m compileall -q git_crawl
python -m pytest tests -q
```

CI runs the same lint, compile, and test gates on every branch push and pull request. It also builds source/wheel distributions and smoke-installs the wheel in a clean consumer virtualenv.

Before publishing or wiring a downstream package to a new commit, run the release-oriented gates locally:

```bash
python -m pip install build
python -m build
python scripts/smoke_consumer_install.py dist/*.whl
```

A downstream package can use `git-crawl` before it is on PyPI by pinning a GitHub tag or commit with a PEP 508 direct reference:

```toml
dependencies = [
  "git-crawl @ git+https://github.com/alex-drocks/git-crawl.git@<commit-sha-or-tag>"
]
```

Prefer tags for repeatability once a tag exists. Raw branch references such as `@main` are convenient but are not reproducible enough for serious downstream testing.

## Data accuracy notes

- Binary file changes are counted as changed files but contribute `0` added and deleted text lines, matching Git's `--numstat` semantics.
- Commit authors are aggregated by contributor identity: GitHub noreply login when available, otherwise lower-cased author email, otherwise author name. For modern GitHub noreply addresses, `author_login` uses the login after `+`; for older noreply addresses, it uses the local part.
- `file_changes` rows classify paths into broad interpretation buckets such as `source`, `lockfile`, `generated`, `spec`, `docs`, `binary`, `vendored`, and `unknown`. The raw additions/deletions remain unchanged; use the classification and `summary.*` generated-like totals to avoid treating tokenizers, OpenAPI specs, lockfiles, or vendored artifacts as hand-authored source churn.
- Aggregate dates use UTC dates derived from Git author timestamps.
- Current lines-of-code snapshots are intentionally not included yet; this tool currently measures commit history/churn, not checked-out source size.
