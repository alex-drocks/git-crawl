# Changelog

This file records user-visible changes and compatibility notes for Git Crawl.

## 0.3.0

- Added `activity.json` as the canonical consumer-facing activity contract using the `git-crawl-activity-v1` schema.
- Credited activity totals exclude binary, lockfile, generated, vendored, and spec/schema-like file changes.
- Skipped noisy churn is reported separately by exclusion reason.

## 0.2.0

- Added package metadata, repository links, classifiers, and search keywords.
- Added bounded jittered exponential backoff for transient GitHub API discovery and git mirror clone/fetch failures.
- GitHub `Retry-After` and `X-RateLimit-Reset` headers are honored before exponential API retry delays.
- Added MIT license terms.

## 0.1.0

- Added public GitHub organization repository discovery.
- Added bare git mirror caching and default-branch history extraction via `git log --numstat`.
- Added JSONL and CSV output datasets for crawl runs, repositories, excluded repositories, commits, file changes, repo failures, org days, repo days, and contributor days.
- Added SQLite incremental state for default-branch crawls.
- Added multi-repository target-day aggregates and deterministic output ordering.
