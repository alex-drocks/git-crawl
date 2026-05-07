from git_crawl.path_classification import classify_path


def test_classify_path_marks_generated_lockfile_spec_docs_source_and_binary_paths():
    assert classify_path("tokenizer/tokenizer.json").path_class == "generated"
    assert classify_path("models/weights.model.json").is_generated_like is True

    lockfile = classify_path("web/package-lock.json")
    assert lockfile.path_class == "lockfile"
    assert lockfile.is_lockfile is True
    assert lockfile.is_generated_like is True

    spec = classify_path("responses-proxy/specs/openai-openapi.yml")
    assert spec.path_class == "spec"
    assert spec.is_generated_like is True

    assert classify_path("docs/usage.md").path_class == "docs"
    assert classify_path("src/app.py").path_class == "source"
    assert classify_path("assets/logo.png", is_binary=True).path_class == "binary"


def test_classify_path_keeps_binary_lockfiles_in_generated_like_lockfile_bucket():
    classification = classify_path("bun.lockb", is_binary=True)

    assert classification.path_class == "lockfile"
    assert classification.is_lockfile is True
    assert classification.is_generated_like is True


def test_classify_path_does_not_treat_build_or_dist_substrings_as_generated():
    assert classify_path("src/build.py").path_class == "source"
    assert classify_path("src/builder.py").path_class == "source"
    assert classify_path("src/distribution.py").path_class == "source"
    assert classify_path("docs/distribution.md").path_class == "docs"
