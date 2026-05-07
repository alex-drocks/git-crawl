import pytest

from git_crawl.config import load_config


def test_load_config_reads_toml_pipeline_settings(tmp_path):
    config_path = tmp_path / "crawler.toml"
    config_path.write_text(
        """
org = "chutesai"
active_since = "2025-01-01T00:00:00Z"
since = "2026-01-01"
ref_scope = "default-branch"
workers = 4
cache_dir = ".cache/mirrors"
output_dir = "out/chutesai"
state_db = ".cache/state.sqlite"

[filters]
max_repos = 10
include_archived = false
include_forks = false

[outputs]
format = "jsonl"
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.org == "chutesai"
    assert config.active_since == "2025-01-01T00:00:00Z"
    assert config.since == "2026-01-01"
    assert config.ref_scope == "default-branch"
    assert config.workers == 4
    assert config.cache_dir == ".cache/mirrors"
    assert config.output_dir == "out/chutesai"
    assert config.state_db == ".cache/state.sqlite"
    assert config.max_repos == 10
    assert config.include_archived is False
    assert config.include_forks is False
    assert config.output_format == "jsonl"


def test_load_config_rejects_bool_values_for_integer_settings(tmp_path):
    config_path = tmp_path / "crawler.toml"
    config_path.write_text(
        """
org = "chutesai"
workers = true
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="integer"):
        load_config(config_path)


def test_load_config_rejects_unsupported_ref_scope(tmp_path):
    config_path = tmp_path / "crawler.toml"
    config_path.write_text(
        """
org = "chutesai"
ref_scope = "everything"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ref_scope"):
        load_config(config_path)


def test_load_config_rejects_unsupported_output_format(tmp_path):
    config_path = tmp_path / "crawler.toml"
    config_path.write_text(
        """
org = "chutesai"

[outputs]
format = "yaml"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="format"):
        load_config(config_path)
