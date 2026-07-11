from datetime import datetime, timezone

from git_crawl.gitlog import parse_author_login, parse_git_log


def test_parse_git_log_extracts_commits_and_numstat_changes():
    output = (
        "\x1eabc123\x1fAlice Example\x1f12345+alice@users.noreply.github.com\x1f"
        "2026-05-04T10:15:30+00:00\x1fparent1 parent2\n"
        "10\t2\tsrc/app.py\n"
        "-\t-\tassets/logo.png\n"
        "\x1edef456\x1fBob Example\x1fbob@example.com\x1f"
        "2026-05-05T11:00:00+00:00\x1f\n"
        "3\t1\tREADME.md\n"
    )

    commits = list(parse_git_log(output, repo="demo"))

    assert [commit.sha for commit in commits] == ["abc123", "def456"]
    assert commits[0].author_name == "Alice Example"
    assert commits[0].author_email == "12345+alice@users.noreply.github.com"
    assert commits[0].author_login == "alice"
    assert commits[0].authored_at == datetime(2026, 5, 4, 10, 15, 30, tzinfo=timezone.utc)
    assert commits[0].parents == ["parent1", "parent2"]
    assert [(c.additions, c.deletions, c.path, c.is_binary) for c in commits[0].changes] == [
        (10, 2, "src/app.py", False),
        (0, 0, "assets/logo.png", True),
    ]
    assert commits[1].author_login is None
    assert commits[1].parents == []


def test_parse_author_login_supports_github_noreply_formats():
    assert parse_author_login("12345+octocat@users.noreply.github.com") == "octocat"
    assert parse_author_login("octocat@users.noreply.github.com") == "octocat"
    assert parse_author_login("octocat@example.com") is None


def test_parse_git_log_preserves_nul_delimited_paths_and_uses_rename_destination():
    output = (
        "\x1eabc123\x1fAlice Example\x1falice@example.com\x1f"
        "2026-05-04T10:15:30+00:00\x1fparent1\n"
        "1\t0\tsrc/tab\tname.py\0"
        "2\t1\tsrc/line\nname.py\0"
        "3\t0\tsrc/control\x1ename.py\0"
        "0\t0\t\0old/package-lock.json\0web/package-lock.json\0"
    )

    [commit] = parse_git_log(output, repo="demo")

    assert [(change.path, change.additions, change.deletions) for change in commit.changes] == [
        ("src/tab\tname.py", 1, 0),
        ("src/line\nname.py", 2, 1),
        ("src/control\x1ename.py", 3, 0),
        ("web/package-lock.json", 0, 0),
    ]


def test_parse_git_log_handles_nul_separator_after_empty_commit():
    output = (
        "\x1eabc123\x1fAlice Example\x1falice@example.com\x1f"
        "2026-05-04T10:15:30+00:00\x1fparent1\0"
        "\x1edef456\x1fBob Example\x1fbob@example.com\x1f"
        "2026-05-03T10:15:30+00:00\x1f\n"
        "1\t0\tREADME.md\0"
    )

    commits = parse_git_log(output, repo="demo")

    assert [commit.sha for commit in commits] == ["abc123", "def456"]
    assert commits[0].parents == ["parent1"]
    assert commits[0].changes == []
