from __future__ import annotations

import email.utils
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from socket import timeout as SocketTimeout
from typing import Callable, Iterable

from .retry import RetryPolicy, sleep_before_retry

GITHUB_API_URL = "https://api.github.com"
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
GITHUB_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class RepoInfo:
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
class RepositoryExclusion:
    repo: RepoInfo
    reason: str


@dataclass(frozen=True)
class GitHubRepoRef:
    owner: str
    repo: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def html_url(self) -> str:
        return f"https://github.com/{self.full_name}"


class GitHubURLParseError(ValueError):
    pass


class GitHubAPIError(RuntimeError):

    def __init__(self, message: str, *, status_code: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.url = url


def _parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _repo_from_api(payload: dict[str, object]) -> RepoInfo:
    return RepoInfo(
        name=str(payload["name"]),
        full_name=str(payload["full_name"]),
        clone_url=str(payload["clone_url"]),
        ssh_url=str(payload["ssh_url"]),
        default_branch=str(payload.get("default_branch") or "main"),
        pushed_at=payload.get("pushed_at"),  # type: ignore[arg-type]
        archived=bool(payload.get("archived", False)),
        fork=bool(payload.get("fork", False)),
        private=bool(payload.get("private", False)),
        language=payload.get("language"),  # type: ignore[arg-type]
    )


def parse_github_repo_url(raw_url: str) -> GitHubRepoRef:
    """Parse common GitHub repository URL forms into an owner/repo reference.

    Repository links may include a trailing ``.git`` suffix or a branch/tree/blob
    path. Issue, pull, and other non-repository links are rejected so callers do
    not accidentally treat arbitrary GitHub pages as crawl targets.
    """
    raw_url = raw_url.strip()
    display_url = _safe_url_for_error(raw_url)
    owner: str | None = None
    repo: str | None = None

    if raw_url.startswith("git@github.com:"):
        path = raw_url.removeprefix("git@github.com:")
        _reject_non_repository_subpath(path, display_url)
        owner, repo = _owner_repo_from_path(path)
    else:
        parsed = urllib.parse.urlparse(raw_url)
        host = (parsed.hostname or "").lower()
        if host != "github.com":
            raise GitHubURLParseError(f"Not a GitHub repository URL: {display_url!r}")
        owner, repo = _owner_repo_from_path(parsed.path)
        _reject_non_repository_subpath(parsed.path, display_url)

    if not owner or not repo:
        raise GitHubURLParseError(f"GitHub repository URL must include owner and repo: {display_url!r}")
    repo = repo.removesuffix(".git")
    _validate_owner_repo(owner, repo, display_url)
    return GitHubRepoRef(owner=owner, repo=repo)


def _safe_url_for_error(raw_url: str) -> str:
    parsed = urllib.parse.urlparse(raw_url)
    if not parsed.scheme or not parsed.netloc:
        return raw_url
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urllib.parse.urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))


def _owner_repo_from_path(path: str) -> tuple[str | None, str | None]:
    parts = [urllib.parse.unquote(part) for part in path.strip("/").split("/") if part]
    if len(parts) < 2:
        return None, None
    return parts[0], parts[1].removesuffix(".git")


def _reject_non_repository_subpath(path: str, display_url: str) -> None:
    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) <= 2:
        return
    allowed_context_prefixes = {"tree", "blob", "commit", "releases"}
    if parts[2] not in allowed_context_prefixes:
        raise GitHubURLParseError(f"Unsupported GitHub repository subpath in URL: {display_url!r}")


def _validate_owner_repo(owner: str, repo: str, display_url: str) -> None:
    if "/" in owner or "/" in repo:
        raise GitHubURLParseError(f"GitHub repository URL contains invalid encoded path separators: {display_url!r}")
    if not GITHUB_OWNER_RE.fullmatch(owner):
        raise GitHubURLParseError(f"GitHub repository URL contains an invalid owner name: {display_url!r}")
    if repo in {".", ".."} or not GITHUB_REPO_RE.fullmatch(repo):
        raise GitHubURLParseError(f"GitHub repository URL contains an invalid repository name: {display_url!r}")


def get_repository(
    owner: str,
    repo: str,
    *,
    token: str | None = None,
    api_url: str = GITHUB_API_URL,
    urlopen: Callable[..., object] | None = None,
    max_attempts: int = 3,
    retry_delay: float = 1.0,
    retry_max_delay: float = 60.0,
    retry_jitter: float = 0.25,
) -> RepoInfo:
    """Fetch repository metadata for one GitHub owner/repo."""
    retry_policy = RetryPolicy(
        max_attempts=max_attempts,
        initial_delay=retry_delay,
        max_delay=retry_max_delay,
        jitter=retry_jitter,
    )
    url = f"{api_url.rstrip('/')}/repos/{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(repo, safe='')}"
    request = urllib.request.Request(url, headers=_headers(token))
    payload = _request_json(
        request,
        urlopen=urlopen or urllib.request.urlopen,
        retry_policy=retry_policy,
    )
    if not isinstance(payload, dict):
        raise GitHubAPIError(f"Unexpected GitHub repository response for {owner}/{repo}: {payload!r}", url=url)
    return _repo_from_api(payload)


def get_repository_from_url(raw_url: str, **kwargs: object) -> RepoInfo:
    """Normalize a GitHub repository URL and fetch its API metadata."""
    ref = parse_github_repo_url(raw_url)
    return get_repository(ref.owner, ref.repo, **kwargs)


def list_repositories_from_urls(urls: Iterable[str], **kwargs: object) -> list[RepoInfo]:
    """Fetch repository metadata for normalized GitHub repository URLs, de-duplicated by full name."""
    repos: list[RepoInfo] = []
    seen_full_names: set[str] = set()
    for raw_url in urls:
        repo = get_repository_from_url(raw_url, **kwargs)
        if repo.full_name in seen_full_names:
            continue
        repos.append(repo)
        seen_full_names.add(repo.full_name)
    return repos


def _headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "git-crawl/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _is_rate_limit_error(error: urllib.error.HTTPError) -> bool:
    remaining = error.headers.get("X-RateLimit-Remaining") if error.headers else None
    return error.code in {403, 429} and remaining == "0"


def _has_retry_after(error: urllib.error.HTTPError) -> bool:
    return error.code in {403, 429, 503} and bool(error.headers and error.headers.get("Retry-After"))


def _is_retryable(error: urllib.error.HTTPError) -> bool:
    return error.code in RETRYABLE_HTTP_STATUSES or _is_rate_limit_error(error) or _has_retry_after(error)


def _retry_after_seconds(error: urllib.error.HTTPError) -> float | None:
    if not error.headers:
        return None

    retry_after = error.headers.get("Retry-After")
    if retry_after:
        parsed = _parse_retry_after(retry_after)
        if parsed is not None:
            return parsed

    if _is_rate_limit_error(error):
        reset_at = error.headers.get("X-RateLimit-Reset")
        if reset_at:
            try:
                return max(0.0, float(reset_at) - time.time())
            except ValueError:
                return None
    return None


def _parse_retry_after(value: str) -> float | None:
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, parsed.timestamp() - time.time())


def _github_error_message(error: urllib.error.HTTPError) -> str:
    body = error.read().decode("utf-8", errors="replace") if error.fp else ""
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {}
    message = payload.get("message") if isinstance(payload, dict) else None
    if message:
        return str(message)
    return error.reason or f"HTTP {error.code}"


def _request_json(
    request: urllib.request.Request,
    *,
    urlopen: Callable[..., object],
    retry_policy: RetryPolicy,
) -> object:
    last_error: BaseException | None = None
    for attempt in range(1, retry_policy.max_attempts + 1):
        override_delay: float | None = None
        apply_jitter = True
        try:
            with urlopen(request, timeout=60) as response:  # type: ignore[attr-defined]
                try:
                    return json.loads(response.read().decode("utf-8"))  # type: ignore[attr-defined]
                except (json.JSONDecodeError, UnicodeDecodeError) as error:
                    last_error = error
                    if attempt >= retry_policy.max_attempts:
                        raise GitHubAPIError(
                            f"GitHub API request returned invalid JSON after {retry_policy.max_attempts} attempts: {error}",
                            url=request.full_url,
                        ) from error
        except urllib.error.HTTPError as error:
            last_error = error
            if attempt >= retry_policy.max_attempts or not _is_retryable(error):
                message = _github_error_message(error)
                raise GitHubAPIError(
                    f"GitHub API request failed with HTTP {error.code}: {message}",
                    status_code=error.code,
                    url=request.full_url,
                ) from error
            override_delay = _retry_after_seconds(error)
            apply_jitter = override_delay is None
        except (urllib.error.URLError, TimeoutError, SocketTimeout) as error:
            last_error = error
            if attempt >= retry_policy.max_attempts:
                raise GitHubAPIError(
                    f"GitHub API request failed after {retry_policy.max_attempts} attempts: {error}",
                    url=request.full_url,
                ) from error

        sleep_before_retry(
            retry_policy,
            attempt,
            override_delay=override_delay,
            apply_jitter=apply_jitter,
        )

    raise GitHubAPIError(
        f"GitHub API request failed after {retry_policy.max_attempts} attempts: {last_error}",
        url=request.full_url,
    )


def list_org_repositories(
    org: str,
    *,
    token: str | None = None,
    api_url: str = GITHUB_API_URL,
    per_page: int = 100,
    repo_type: str = "public",
    urlopen: Callable[..., object] | None = None,
    max_attempts: int = 3,
    retry_delay: float = 1.0,
    retry_max_delay: float = 60.0,
    retry_jitter: float = 0.25,
) -> list[RepoInfo]:
    """List organization repositories via REST pagination, requesting public repos by default."""
    if repo_type not in {"public", "all", "member", "private", "forks", "sources"}:
        raise ValueError(f"Unsupported GitHub organization repository type: {repo_type}")
    return _list_repositories_for_owner_path(
        owner=org,
        owner_path="orgs",
        token=token,
        api_url=api_url,
        per_page=per_page,
        repo_type=repo_type,
        urlopen=urlopen,
        max_attempts=max_attempts,
        retry_delay=retry_delay,
        retry_max_delay=retry_max_delay,
        retry_jitter=retry_jitter,
    )


def list_user_repositories(
    user: str,
    *,
    token: str | None = None,
    api_url: str = GITHUB_API_URL,
    per_page: int = 100,
    repo_type: str = "owner",
    urlopen: Callable[..., object] | None = None,
    max_attempts: int = 3,
    retry_delay: float = 1.0,
    retry_max_delay: float = 60.0,
    retry_jitter: float = 0.25,
) -> list[RepoInfo]:
    """List repositories for a GitHub user login via REST pagination."""
    if repo_type not in {"all", "owner", "member"}:
        raise ValueError(f"Unsupported GitHub user repository type: {repo_type}")
    return _list_repositories_for_owner_path(
        owner=user,
        owner_path="users",
        token=token,
        api_url=api_url,
        per_page=per_page,
        repo_type=repo_type,
        urlopen=urlopen,
        max_attempts=max_attempts,
        retry_delay=retry_delay,
        retry_max_delay=retry_max_delay,
        retry_jitter=retry_jitter,
    )


def list_owner_repositories(
    owner: str,
    *,
    owner_type: str = "auto",
    token: str | None = None,
    api_url: str = GITHUB_API_URL,
    per_page: int = 100,
    urlopen: Callable[..., object] | None = None,
    max_attempts: int = 3,
    retry_delay: float = 1.0,
    retry_max_delay: float = 60.0,
    retry_jitter: float = 0.25,
) -> list[RepoInfo]:
    """List repositories for a GitHub owner root, accepting org or user logins.

    ``owner_type='auto'`` tries the organization endpoint first, then falls back
    to the public user endpoint only when GitHub reports the org was not found.
    """
    if owner_type == "org":
        return list_org_repositories(
            owner,
            token=token,
            api_url=api_url,
            per_page=per_page,
            urlopen=urlopen,
            max_attempts=max_attempts,
            retry_delay=retry_delay,
            retry_max_delay=retry_max_delay,
            retry_jitter=retry_jitter,
        )
    if owner_type == "user":
        return list_user_repositories(
            owner,
            token=token,
            api_url=api_url,
            per_page=per_page,
            urlopen=urlopen,
            max_attempts=max_attempts,
            retry_delay=retry_delay,
            retry_max_delay=retry_max_delay,
            retry_jitter=retry_jitter,
        )
    if owner_type != "auto":
        raise ValueError("owner_type must be one of 'auto', 'org', or 'user'")

    try:
        return list_org_repositories(
            owner,
            token=token,
            api_url=api_url,
            per_page=per_page,
            urlopen=urlopen,
            max_attempts=max_attempts,
            retry_delay=retry_delay,
            retry_max_delay=retry_max_delay,
            retry_jitter=retry_jitter,
        )
    except GitHubAPIError as error:
        if error.status_code != 404:
            raise
    return list_user_repositories(
        owner,
        token=token,
        api_url=api_url,
        per_page=per_page,
        urlopen=urlopen,
        max_attempts=max_attempts,
        retry_delay=retry_delay,
        retry_max_delay=retry_max_delay,
        retry_jitter=retry_jitter,
    )


def _list_repositories_for_owner_path(
    *,
    owner: str,
    owner_path: str,
    token: str | None,
    api_url: str,
    per_page: int,
    repo_type: str,
    urlopen: Callable[..., object] | None,
    max_attempts: int,
    retry_delay: float,
    retry_max_delay: float,
    retry_jitter: float,
) -> list[RepoInfo]:
    if per_page < 1 or per_page > 100:
        raise ValueError("per_page must be between 1 and 100 for GitHub REST pagination")
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    retry_policy = RetryPolicy(
        max_attempts=max_attempts,
        initial_delay=retry_delay,
        max_delay=retry_max_delay,
        jitter=retry_jitter,
    )

    open_url = urlopen or urllib.request.urlopen
    repos: list[RepoInfo] = []
    seen_full_names: set[str] = set()
    page = 1
    while True:
        query = urllib.parse.urlencode(
            {
                "per_page": per_page,
                "page": page,
                "type": repo_type,
                "sort": "full_name",
                "direction": "asc",
            }
        )
        encoded_owner = urllib.parse.quote(owner, safe="")
        url = f"{api_url.rstrip('/')}/{owner_path}/{encoded_owner}/repos?{query}"
        request = urllib.request.Request(url, headers=_headers(token))
        payload = _request_json(
            request,
            urlopen=open_url,
            retry_policy=retry_policy,
        )

        if not isinstance(payload, list):
            raise GitHubAPIError(f"Unexpected GitHub repository response for {owner}: {payload!r}", url=url)

        for item in payload:
            repo = _repo_from_api(item)
            if repo.full_name in seen_full_names:
                continue
            repos.append(repo)
            seen_full_names.add(repo.full_name)
        if len(payload) < per_page:
            break
        page += 1

    return repos


def select_active_repositories(
    repos: Iterable[RepoInfo],
    *,
    active_since: str | None = None,
    include_archived: bool = False,
    include_forks: bool = False,
    max_repos: int | None = None,
) -> list[RepoInfo]:
    """Select public, non-archived, non-fork repos by default; apply active_since when set."""
    selected, _excluded = partition_repositories(
        repos,
        active_since=active_since,
        include_archived=include_archived,
        include_forks=include_forks,
        max_repos=max_repos,
    )
    return selected


def partition_repositories(
    repos: Iterable[RepoInfo],
    *,
    active_since: str | None = None,
    include_archived: bool = False,
    include_forks: bool = False,
    max_repos: int | None = None,
) -> tuple[list[RepoInfo], list[RepositoryExclusion]]:
    """Select crawlable repositories and preserve excluded repos with explicit reasons."""
    active_cutoff = _parse_github_datetime(active_since)

    selected: list[RepoInfo] = []
    excluded: list[RepositoryExclusion] = []
    for repo in repos:
        exclusion_reason = _repository_exclusion_reason(
            repo,
            active_cutoff=active_cutoff,
            include_archived=include_archived,
            include_forks=include_forks,
        )
        if exclusion_reason:
            excluded.append(RepositoryExclusion(repo=repo, reason=exclusion_reason))
            continue
        selected.append(repo)

    selected = _sort_repositories_for_crawl(selected)
    if max_repos is not None and len(selected) > max_repos:
        excluded.extend(
            RepositoryExclusion(repo=repo, reason="over_max_repos")
            for repo in selected[max_repos:]
        )
        selected = selected[:max_repos]
    return selected, excluded


def _repository_exclusion_reason(
    repo: RepoInfo,
    *,
    active_cutoff: datetime | None,
    include_archived: bool,
    include_forks: bool,
) -> str | None:
    if repo.private:
        return "private"
    if repo.archived and not include_archived:
        return "archived"
    if repo.fork and not include_forks:
        return "fork"
    pushed_at = _parse_github_datetime(repo.pushed_at)
    if active_cutoff is not None and (pushed_at is None or pushed_at < active_cutoff):
        return "inactive_before_active_since"
    return None


def _sort_repositories_for_crawl(repos: Iterable[RepoInfo]) -> list[RepoInfo]:
    selected = sorted(repos, key=lambda repo: repo.full_name)
    selected.sort(
        key=lambda repo: _parse_github_datetime(repo.pushed_at) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return selected


def token_from_env(name: str = "GITHUB_TOKEN") -> str | None:
    value = os.environ.get(name)
    return value if value else None
