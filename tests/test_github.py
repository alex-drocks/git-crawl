from git_crawl.github import RepoInfo, select_active_repositories


def test_select_active_repositories_filters_archived_forks_and_old_repos_then_sorts_by_push_time():
    repos = [
        RepoInfo(
            name="old",
            full_name="chutesai/old",
            clone_url="https://github.com/chutesai/old.git",
            ssh_url="git@github.com:chutesai/old.git",
            default_branch="main",
            pushed_at="2025-01-01T00:00:00Z",
            archived=False,
            fork=False,
            private=False,
            language="Python",
        ),
        RepoInfo(
            name="fresh",
            full_name="chutesai/fresh",
            clone_url="https://github.com/chutesai/fresh.git",
            ssh_url="git@github.com:chutesai/fresh.git",
            default_branch="main",
            pushed_at="2026-05-01T00:00:00Z",
            archived=False,
            fork=False,
            private=False,
            language="Go",
        ),
        RepoInfo(
            name="newer",
            full_name="chutesai/newer",
            clone_url="https://github.com/chutesai/newer.git",
            ssh_url="git@github.com:chutesai/newer.git",
            default_branch="main",
            pushed_at="2026-05-03T00:00:00Z",
            archived=False,
            fork=False,
            private=False,
            language="TypeScript",
        ),
        RepoInfo(
            name="archived",
            full_name="chutesai/archived",
            clone_url="https://github.com/chutesai/archived.git",
            ssh_url="git@github.com:chutesai/archived.git",
            default_branch="main",
            pushed_at="2026-05-04T00:00:00Z",
            archived=True,
            fork=False,
            private=False,
            language=None,
        ),
        RepoInfo(
            name="forked",
            full_name="chutesai/forked",
            clone_url="https://github.com/chutesai/forked.git",
            ssh_url="git@github.com:chutesai/forked.git",
            default_branch="main",
            pushed_at="2026-05-04T00:00:00Z",
            archived=False,
            fork=True,
            private=False,
            language=None,
        ),
        RepoInfo(
            name="private",
            full_name="chutesai/private",
            clone_url="https://github.com/chutesai/private.git",
            ssh_url="git@github.com:chutesai/private.git",
            default_branch="main",
            pushed_at="2026-05-05T00:00:00Z",
            archived=False,
            fork=False,
            private=True,
            language="Python",
        ),
    ]

    selected = select_active_repositories(
        repos,
        active_since="2026-01-01T00:00:00Z",
        include_archived=False,
        include_forks=False,
        max_repos=2,
    )

    assert [repo.name for repo in selected] == ["newer", "fresh"]




def test_select_active_repositories_breaks_equal_push_time_ties_by_full_name():
    repos = [
        RepoInfo(
            name="web",
            full_name="chutesai/web",
            clone_url="https://github.com/chutesai/web.git",
            ssh_url="git@github.com:chutesai/web.git",
            default_branch="main",
            pushed_at="2026-05-01T00:00:00Z",
            archived=False,
            fork=False,
            private=False,
            language="TypeScript",
        ),
        RepoInfo(
            name="api",
            full_name="chutesai/api",
            clone_url="https://github.com/chutesai/api.git",
            ssh_url="git@github.com:chutesai/api.git",
            default_branch="main",
            pushed_at="2026-05-01T00:00:00Z",
            archived=False,
            fork=False,
            private=False,
            language="Python",
        ),
    ]

    selected = select_active_repositories(repos, max_repos=1)

    assert [repo.full_name for repo in selected] == ["chutesai/api"]


def test_select_active_repositories_accepts_date_only_active_since_as_utc_midnight():
    repo = RepoInfo(
        name="fresh",
        full_name="chutesai/fresh",
        clone_url="https://github.com/chutesai/fresh.git",
        ssh_url="git@github.com:chutesai/fresh.git",
        default_branch="main",
        pushed_at="2026-01-01T00:00:00Z",
        archived=False,
        fork=False,
        private=False,
        language="Python",
    )

    selected = select_active_repositories([repo], active_since="2026-01-01")

    assert selected == [repo]
