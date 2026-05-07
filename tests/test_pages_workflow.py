from pathlib import Path


def test_repository_does_not_ship_active_scheduled_pages_crawler():
    """The reusable package must not make Alex run a central public crawl."""
    assert not Path(".github/workflows/crawl-and-publish-pages.yml").exists()
    assert Path(".github/workflows/ci.yml").exists()
