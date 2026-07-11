import json
import urllib.error
import urllib.parse

import pytest

from git_crawl.github import (
    GitHubURLParseError,
    get_repository_from_url,
    list_repositories_from_urls,
    parse_github_repo_url,
)

class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


def _repo_payload(owner="chutesai", name="api"):
    return {
        "name": name,
        "full_name": f"{owner}/{name}",
        "clone_url": f"https://github.com/{owner}/{name}.git",
        "ssh_url": f"git@github.com:{owner}/{name}.git",
        "default_branch": "main",
        "pushed_at": "2026-05-01T00:00:00Z",
        "archived": False,
        "fork": False,
        "private": False,
        "language": "Python",
    }


@pytest.mark.parametrize(
    ("raw", "owner", "repo"),
    [
        ("https://github.com/ChutesAI/api", "ChutesAI", "api"),
        ("https://github.com/chutesai/api.git", "chutesai", "api"),
        ("https://github.com/chutesai/api/tree/main", "chutesai", "api"),
        ("git@github.com:chutesai/api.git", "chutesai", "api"),
        ("ssh://git@github.com/chutesai/api.git", "chutesai", "api"),
    ],
)
def test_parse_github_repo_url_normalizes_common_repository_links(raw, owner, repo):
    parsed = parse_github_repo_url(raw)

    assert parsed.owner == owner
    assert parsed.repo == repo
    assert parsed.full_name == f"{owner}/{repo}"
    assert parsed.html_url == f"https://github.com/{owner}/{repo}"


@pytest.mark.parametrize(
    "raw",
    [
        "https://github.com/chutesai",
        "https://gitlab.com/chutesai/api",
        "not a url",
        "https://github.com/chutesai/api/issues/1",
        "https://github.com/chutesai/api/%69ssues/1",
        "https://github.com:notaport/chutesai/api",
        "https://github.com:99999/chutesai/api",
        "https://github.com/chutesai%2Fextra/api",
        "https://github.com/chutesai/api%2Fissues",
        "git@github.com:chutesai/api/issues/1",
    ],
)
def test_parse_github_repo_url_rejects_non_repository_links(raw):
    with pytest.raises(GitHubURLParseError):
        parse_github_repo_url(raw)


def test_parse_github_repo_url_redacts_userinfo_from_errors():
    with pytest.raises(GitHubURLParseError) as exc_info:
        parse_github_repo_url("https://x-access-token:SECRET123@github.com/chutesai/api/issues/1")

    message = str(exc_info.value)
    assert "SECRET123" not in message
    assert "x-access-token" not in message


def test_parse_github_repo_url_redacts_userinfo_from_malformed_host_errors():
    with pytest.raises(GitHubURLParseError) as exc_info:
        parse_github_repo_url("https://x-access-token:SECRET123@[github.com/chutesai/api")

    message = str(exc_info.value)
    assert "SECRET123" not in message
    assert "x-access-token" not in message


def test_get_repository_from_url_fetches_metadata_for_normalized_repo_link():
    requested_urls = []

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        return FakeResponse(json.dumps(_repo_payload()).encode("utf-8"))

    repo = get_repository_from_url(
        "https://github.com/chutesai/api/tree/main",
        urlopen=fake_urlopen,
        max_attempts=1,
        retry_delay=0,
    )

    assert repo.full_name == "chutesai/api"
    parsed_url = urllib.parse.urlparse(requested_urls[0])
    assert parsed_url.path == "/repos/chutesai/api"


def test_list_repositories_from_urls_stops_after_max_unique_repositories_before_later_404s():
    requested_paths = []

    def fake_urlopen(request, timeout):
        parsed_url = urllib.parse.urlparse(request.full_url)
        requested_paths.append(parsed_url.path)
        if parsed_url.path == "/repos/dead/missing":
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", hdrs={}, fp=None)
        owner, name = parsed_url.path.removeprefix("/repos/").split("/", 1)
        return FakeResponse(json.dumps(_repo_payload(owner=owner, name=name)).encode("utf-8"))

    repos = list_repositories_from_urls(
        [
            "https://github.com/alice/api",
            "https://github.com/alice/api",
            "https://github.com/bob/web",
            "https://github.com/dead/missing",
        ],
        max_repos=2,
        urlopen=fake_urlopen,
        max_attempts=1,
        retry_delay=0,
    )

    assert [repo.full_name for repo in repos] == ["alice/api", "bob/web"]
    assert requested_paths == ["/repos/alice/api", "/repos/bob/web"]
