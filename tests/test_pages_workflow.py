from pathlib import Path


def test_repository_does_not_ship_active_scheduled_pages_crawler():
    """The reusable package must not make Alex run a central public crawl."""
    workflow_dir = Path(".github/workflows")
    workflow_paths = sorted([*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")])

    assert Path(".github/workflows/ci.yml").exists()
    for workflow_path in workflow_paths:
        workflow_text = workflow_path.read_text(encoding="utf-8").lower()
        assert "crawl-and-publish-pages" not in workflow_path.name
        assert "schedule:" not in workflow_text
        assert "deploy-pages" not in workflow_text
        assert "upload-pages-artifact" not in workflow_text
        assert "configure-pages" not in workflow_text
        assert "github-pages" not in workflow_text
