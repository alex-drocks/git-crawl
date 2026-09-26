# Changelog

This file records user-visible changes and compatibility notes for Git Crawl.

## Unreleased

## 0.3.3

- Decode Git output as UTF-8 with replacement characters, so a path or author identity that is not valid UTF-8
  anywhere in a repository's history no longer fails the whole repository crawl. Literal carriage returns are kept.
- Cache only branches and tags in local mirrors. New mirrors use `git clone --bare` instead of `git clone --mirror`,
  and mirrors created by earlier versions drop their extra refs on the next fetch. GitHub pull request refs
  (`refs/pull/*`) are no longer downloaded, and `--ref-scope all-refs` no longer counts unmerged pull request
  commits. Existing cache directories keep working without a rebuild.
- Retry GitHub API requests and git clone/fetch five times by default, backing off from 2 seconds, so a short
  outage no longer fails a repository after three attempts within about 3 seconds. Explicit retry arguments are
  unchanged.
- Write output files to temporary siblings and rename them into place together once all are written. Readers no
  longer see truncated files mid-write, and a failed write leaves the previous outputs intact.
- Pin the Ruff rule selection so newer Ruff releases that enable more rules by default do not fail CI.

## 0.3.2

- Preserve literal Git paths containing tabs or newlines and expose rename destinations as the changed path, keeping
  downstream path classification accurate.
- Reject malformed GitHub URLs consistently and reject unsupported repository subpaths even when their route names are
  percent-encoded.

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
