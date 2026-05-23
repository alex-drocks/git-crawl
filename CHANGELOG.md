# Changelog

All notable changes to Git Crawl will be documented in this file.

The project follows semantic versioning once tagged releases begin.

## Unreleased

No changes yet.

## 0.3.0

### Added

- Add canonical `activity.json` credited activity output with source-like totals, active-day averages, and skipped noisy churn by reason.

## 0.2.0

### Added

- Harden CI with committed-whitespace checks, Ruff linting, package compilation, and the existing pytest suite.
- Add explicit Ruff configuration for the Python 3.12 codebase.
- Add MIT license text.
- Add package metadata for repository links, classifiers, and search keywords.
- Add bounded jittered exponential backoff for transient GitHub API discovery and git mirror clone/fetch failures.
- Use GitHub `Retry-After` and `X-RateLimit-Reset` headers before falling back to exponential API retry delays.

## 0.1.0 - Initial development

### Added

- Public GitHub organization repository discovery.
- Bare git mirror caching and default-branch history extraction via `git log --numstat`.
- JSONL and CSV outputs for crawl runs, repositories, excluded repositories, commits, file changes, repo failures, org days, repo days, and contributor days.
- SQLite incremental state for default-branch crawls.
- Multi-repo organization-day productivity aggregates and deterministic output ordering.
