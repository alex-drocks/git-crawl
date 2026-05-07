import tomllib
from pathlib import Path


def test_project_metadata_targets_python_312_only():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["requires-python"] == ">=3.12"
    classifiers = pyproject["project"]["classifiers"]
    assert "Programming Language :: Python :: 3.12" in classifiers
    assert "Programming Language :: Python :: 3.11" not in classifiers
    assert pyproject["tool"]["ruff"]["target-version"] == "py312"
