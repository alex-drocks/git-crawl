import json
import urllib.error
import urllib.parse

import pytest

from git_crawl import github
from git_crawl.github import GitHubAPIError, list_org_repositories, list_owner_repositories, list_user_repositories


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


def test_list_org_repositories_retries_transient_api_failures_and_requests_public_repos():
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                502,
                "Bad Gateway",
                hdrs={},
                fp=None,
            )
        return FakeResponse(
            b"""[
              {
                "name": "api",
                "full_name": "chutesai/api",
                "clone_url": "https://github.com/chutesai/api.git",
                "ssh_url": "git@github.com:chutesai/api.git",
                "default_branch": "main",
                "pushed_at": "2026-05-01T00:00:00Z",
                "archived": false,
                "fork": false,
                "private": false,
                "language": "Python"
              }
            ]"""
        )

    repos = list_org_repositories(
        "chutesai",
        urlopen=fake_urlopen,
        max_attempts=2,
        retry_delay=0,
    )

    assert [repo.full_name for repo in repos] == ["chutesai/api"]
    assert len(calls) == 2
    assert "type=public" in calls[-1].full_url


def test_list_org_repositories_honors_retry_after_before_exponential_backoff(monkeypatch):
    calls = []
    sleeps = []

    monkeypatch.setattr(github.time, "sleep", lambda seconds: sleeps.append(seconds))

    def fake_sleep(policy, failed_attempt, *, override_delay=None, apply_jitter=True):
        sleeps.append(
            policy.delay_for_attempt(
                failed_attempt,
                override_delay=override_delay,
                apply_jitter=apply_jitter,
            )
        )

    monkeypatch.setattr(github, "sleep_before_retry", fake_sleep, raising=False)

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                hdrs={"Retry-After": "7"},
                fp=None,
            )
        return FakeResponse(json.dumps([_repo_payload("api")]).encode("utf-8"))

    repos = list_org_repositories(
        "chutesai",
        urlopen=fake_urlopen,
        max_attempts=2,
        retry_delay=1,
    )

    assert [repo.full_name for repo in repos] == ["chutesai/api"]
    assert sleeps == [7.0]


def test_list_org_repositories_honors_rate_limit_reset_header(monkeypatch):
    calls = []
    sleeps = []

    monkeypatch.setattr(github.time, "time", lambda: 1_000.0)
    monkeypatch.setattr(github.time, "sleep", lambda seconds: sleeps.append(seconds))

    def fake_sleep(policy, failed_attempt, *, override_delay=None, apply_jitter=True):
        sleeps.append(
            policy.delay_for_attempt(
                failed_attempt,
                override_delay=override_delay,
                apply_jitter=apply_jitter,
            )
        )

    monkeypatch.setattr(github, "sleep_before_retry", fake_sleep, raising=False)

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                403,
                "API rate limit exceeded",
                hdrs={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1005"},
                fp=None,
            )
        return FakeResponse(json.dumps([_repo_payload("api")]).encode("utf-8"))

    repos = list_org_repositories(
        "chutesai",
        urlopen=fake_urlopen,
        max_attempts=2,
        retry_delay=1,
    )

    assert [repo.full_name for repo in repos] == ["chutesai/api"]
    assert sleeps == [5.0]


def test_list_org_repositories_retries_secondary_rate_limits_with_retry_after(monkeypatch):
    calls = []
    sleeps = []

    monkeypatch.setattr(github.time, "sleep", lambda seconds: sleeps.append(seconds))

    def fake_sleep(policy, failed_attempt, *, override_delay=None, apply_jitter=True):
        sleeps.append(
            policy.delay_for_attempt(
                failed_attempt,
                override_delay=override_delay,
                apply_jitter=apply_jitter,
            )
        )

    monkeypatch.setattr(github, "sleep_before_retry", fake_sleep, raising=False)

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                403,
                "secondary rate limit",
                hdrs={"Retry-After": "3"},
                fp=None,
            )
        return FakeResponse(json.dumps([_repo_payload("api")]).encode("utf-8"))

    repos = list_org_repositories(
        "chutesai",
        urlopen=fake_urlopen,
        max_attempts=2,
        retry_delay=1,
    )

    assert [repo.full_name for repo in repos] == ["chutesai/api"]
    assert sleeps == [3.0]


def test_list_org_repositories_uses_jittered_exponential_backoff(monkeypatch):
    calls = []
    sleeps = []
    jitter_fractions = iter([0.0, 0.5, 1.0])

    monkeypatch.setattr(github.time, "sleep", lambda seconds: sleeps.append(seconds))

    def fake_sleep(policy, failed_attempt, *, override_delay=None, apply_jitter=True):
        sleeps.append(
            policy.delay_for_attempt(
                failed_attempt,
                override_delay=override_delay,
                apply_jitter=apply_jitter,
                random_fraction=next(jitter_fractions),
            )
        )

    monkeypatch.setattr(github, "sleep_before_retry", fake_sleep, raising=False)

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) < 4:
            raise urllib.error.HTTPError(
                request.full_url,
                502,
                "Bad Gateway",
                hdrs={},
                fp=None,
            )
        return FakeResponse(json.dumps([_repo_payload("api")]).encode("utf-8"))

    repos = list_org_repositories(
        "chutesai",
        urlopen=fake_urlopen,
        max_attempts=4,
        retry_delay=2,
        retry_jitter=0.25,
    )

    assert [repo.full_name for repo in repos] == ["chutesai/api"]
    assert sleeps == [1.5, 4.0, 10.0]


def _repo_payload(name, pushed_at="2026-05-01T00:00:00Z", owner="chutesai"):
    return {
        "name": name,
        "full_name": f"{owner}/{name}",
        "clone_url": f"https://github.com/{owner}/{name}.git",
        "ssh_url": f"git@github.com:{owner}/{name}.git",
        "default_branch": "main",
        "pushed_at": pushed_at,
        "archived": False,
        "fork": False,
        "private": False,
        "language": "Python",
    }


def test_list_org_repositories_uses_stable_pagination_and_deduplicates_by_full_name():
    pages = {
        1: [_repo_payload("api"), _repo_payload("web")],
        2: [_repo_payload("web"), _repo_payload("sdk")],
        3: [],
    }
    requested_urls = []

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
        page = int(query["page"][0])
        return FakeResponse(json.dumps(pages[page]).encode("utf-8"))

    repos = list_org_repositories(
        "chutesai",
        urlopen=fake_urlopen,
        per_page=2,
        max_attempts=1,
        retry_delay=0,
    )

    assert [repo.full_name for repo in repos] == ["chutesai/api", "chutesai/web", "chutesai/sdk"]
    assert all("sort=full_name" in url for url in requested_urls)
    assert all("direction=asc" in url for url in requested_urls)


def test_list_org_repositories_retries_malformed_json_response():
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            return FakeResponse(b"{not valid json")
        return FakeResponse(json.dumps([_repo_payload("api")]).encode("utf-8"))

    repos = list_org_repositories(
        "chutesai",
        urlopen=fake_urlopen,
        max_attempts=2,
        retry_delay=0,
    )

    assert [repo.full_name for repo in repos] == ["chutesai/api"]
    assert len(calls) == 2


def test_list_org_repositories_wraps_repeated_malformed_json_failures():
    def fake_urlopen(request, timeout):
        return FakeResponse(b"{not valid json")

    with pytest.raises(GitHubAPIError, match="invalid JSON"):
        list_org_repositories(
            "chutesai",
            urlopen=fake_urlopen,
            max_attempts=2,
            retry_delay=0,
        )


def test_list_owner_repositories_auto_falls_back_from_org_to_user_owner_root():
    requested_paths = []

    def fake_urlopen(request, timeout):
        parsed = urllib.parse.urlparse(request.full_url)
        requested_paths.append(parsed.path)
        if parsed.path == "/orgs/alice/repos":
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Not Found",
                hdrs={},
                fp=None,
            )
        assert parsed.path == "/users/alice/repos"
        return FakeResponse(json.dumps([_repo_payload("portfolio", owner="alice")]).encode("utf-8"))

    repos = list_owner_repositories(
        "alice",
        urlopen=fake_urlopen,
        max_attempts=1,
        retry_delay=0,
    )

    assert requested_paths == ["/orgs/alice/repos", "/users/alice/repos"]
    assert [repo.full_name for repo in repos] == ["alice/portfolio"]


def test_list_owner_repositories_can_request_user_or_org_owner_type_directly():
    requested_paths = []

    def fake_urlopen(request, timeout):
        parsed = urllib.parse.urlparse(request.full_url)
        requested_paths.append(parsed.path)
        return FakeResponse(json.dumps([_repo_payload("profile", owner="alice")]).encode("utf-8"))

    repos = list_owner_repositories(
        "alice",
        owner_type="user",
        urlopen=fake_urlopen,
        max_attempts=1,
        retry_delay=0,
    )

    assert requested_paths == ["/users/alice/repos"]
    assert [repo.full_name for repo in repos] == ["alice/profile"]


def test_list_user_repositories_uses_public_user_endpoint():
    requested_urls = []

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        return FakeResponse(json.dumps([_repo_payload("profile", owner="alice")]).encode("utf-8"))

    repos = list_user_repositories(
        "alice",
        urlopen=fake_urlopen,
        max_attempts=1,
        retry_delay=0,
    )

    parsed = urllib.parse.urlparse(requested_urls[0])
    assert parsed.path == "/users/alice/repos"
    assert "type=owner" in requested_urls[0]
    assert [repo.full_name for repo in repos] == ["alice/profile"]


def test_list_owner_repositories_rejects_unknown_owner_type():
    with pytest.raises(ValueError, match="owner_type"):
        list_owner_repositories("alice", owner_type="team")


def test_list_org_repositories_rejects_per_page_values_github_would_truncate():
    with pytest.raises(ValueError, match="per_page"):
        list_org_repositories("chutesai", per_page=101)
