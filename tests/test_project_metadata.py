import tomllib
from pathlib import Path


def test_project_metadata_targets_python_312_only():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["requires-python"] == ">=3.12"
    classifiers = pyproject["project"]["classifiers"]
    assert "Programming Language :: Python :: 3.12" in classifiers
    assert "Programming Language :: Python :: 3.11" not in classifiers
    assert pyproject["tool"]["ruff"]["target-version"] == "py312"


def test_source_distribution_manifest_includes_hardening_docs_and_scripts():
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")

    assert "recursive-include docs" in manifest
    assert "recursive-include scripts" in manifest
    assert "recursive-include tests" in manifest


def test_core_package_does_not_ship_static_dashboard_module():
    assert not Path("git_crawl/static_api.py").exists()
