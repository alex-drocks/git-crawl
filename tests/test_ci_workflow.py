from pathlib import Path


def test_ci_workflow_uses_python_312_runtime_and_pip_cache():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "permissions:" in workflow
    assert "contents: read" in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    assert "timeout-minutes: 10" in workflow
    assert "actions/setup-python@v6" in workflow
    assert 'python-version: "3.12"' in workflow
    assert 'cache: "pip"' in workflow
    assert "cache-dependency-path: pyproject.toml" in workflow
    assert "3.11" not in workflow


def test_ci_workflow_builds_distributions_and_smoke_installs_clean_wheel():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Install build backend" in workflow
    assert "python -m pip install build" in workflow
    assert "Build sdist and wheel" in workflow
    assert "python -m build" in workflow
    assert "Smoke install wheel in clean consumer venv" in workflow
    assert "python scripts/smoke_consumer_install.py dist/*.whl" in workflow
