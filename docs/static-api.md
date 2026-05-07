# Static API and KPI dashboard

`git-crawl` can convert a crawl output directory into a static API tree with JSON manifests, raw data files, and a human-friendly HTML KPI dashboard.

This is intentionally static, not a hosted query service. You run the crawl wherever you want, generate the static files, and publish them only if you want to. The package does **not** include an active scheduled GitHub Pages workflow, so adopting `git-crawl` does not make Alex operate or pay for a central crawler.

## Build locally

```bash
python -m git_crawl.cli crawl-org chutesai \
  --max-repos 1 \
  --since 2026-01-01 \
  --output-dir /tmp/git-crawl-out \
  --cache-dir .cache/git-crawl/mirrors \
  --workers 2 \
  --format all

python -m git_crawl.cli build-static-api chutesai \
  --data-dir /tmp/git-crawl-out \
  --site-dir /tmp/git-crawl-site \
  --run-label latest \
  --base-url https://example.com/git-crawl
```

Then inspect:

```text
/tmp/git-crawl-site/index.html
/tmp/git-crawl-site/chutesai/latest/dashboard.html
/tmp/git-crawl-site/api/chutesai/latest.json
```

## Publish only on your own infra

If you want a public dashboard/API, publish the generated `site/` directory with infrastructure you control, for example:

- your own GitHub Actions workflow and GitHub Pages project;
- a cron job on a VPS;
- Cloudflare Pages, Netlify, Vercel, S3, or another static host;
- a private artifact bucket consumed by an internal app.

Keep tokens out of source code. Use environment variables or your runner's secret store, and reference only secret names in workflow/config files.

## Generated endpoints

For a static host rooted at `https://example.com/git-crawl`, a target label `chutesai`, and a run label `latest`, useful endpoints are:

```text
/index.html
/index.json
/api/index.json
/api/chutesai/latest.json
/chutesai/latest/dashboard.html
/chutesai/latest/index.json
/chutesai/latest/summary.json
/chutesai/latest/summary.md
/chutesai/latest/output_manifest.json
/chutesai/latest/crawl_runs.jsonl
/chutesai/latest/repositories.jsonl
/chutesai/latest/excluded_repositories.jsonl
/chutesai/latest/commits.jsonl
/chutesai/latest/file_changes.jsonl
/chutesai/latest/org_days.jsonl
/chutesai/latest/repo_days.jsonl
/chutesai/latest/contributor_days.jsonl
/chutesai/latest/repo_failures.jsonl
```

CSV siblings are published too when the crawl writes them, for example `/chutesai/latest/org_days.csv`.

`/api/chutesai/latest.json` is the main manifest. It includes:

- API version;
- generated timestamp;
- target/org and run label;
- crawl run status and totals when `summary.json` is present;
- output schema version and `output_manifest.json` endpoint when present;
- dashboard endpoint for the human-friendly KPI page;
- calendar span and average metrics when present;
- every copied output file with path, format, byte size, and URL when `--base-url` is configured.

`/index.html` is a root dashboard for the latest published run. `/chutesai/latest/dashboard.html` is the canonical run-scoped dashboard. Both are static HTML pages that render headline KPIs, calendarized averages, source-like versus generated-like churn, top repositories, top paths, path-class mix, caveats, and links to raw JSON/JSONL files.

## Incremental-state caveat for public `latest` datasets

A public `latest` API usually should represent complete current crawl output. For default-branch crawls, stateful incremental mode can emit only new rows after the previous matching run, so a later `latest/summary.json` could misleadingly show zero commits when nothing changed.

If you publish a public `latest` dataset, prefer one of these approaches:

- run without `--state-db` and use a persistent mirror cache for speed;
- keep raw incremental outputs private and publish a compact materialized summary built from your own store;
- publish run-labeled delta datasets and make the delta semantics explicit in the dashboard/API.
