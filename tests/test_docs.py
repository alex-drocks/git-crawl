from pathlib import Path


def test_metric_definitions_document_core_pipeline_semantics():
    text = Path("docs/metrics.md").read_text(encoding="utf-8")

    expected_phrases = [
        "default branch",
        "private repositories are excluded",
        "UTC",
        "commits",
        "unique_contributors",
        "lines_added",
        "lines_deleted",
        "files_changed",
        "org_days",
        "repositories",
        "raw commits",
        "file changes",
    ]
    for phrase in expected_phrases:
        assert phrase in text
