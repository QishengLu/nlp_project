"""env_fingerprint sanity: all required keys present, optional ones degrade."""
from __future__ import annotations

from apr_agent.env_fingerprint import env_fingerprint


def test_fingerprint_contains_all_keys():
    fp = env_fingerprint(
        model_id="qwen3-coder-30b-a3b-instruct",
        defects4j_version="2.0.1",
        d4j_subset="2.0",
    )
    required = {
        "git_sha", "defects4j_version", "defects4j_commit_sha", "d4j_subset",
        "java_version", "tz", "python_version", "apr_agent_version",
        "model_id", "host",
    }
    assert required <= set(fp.keys())
    assert fp["model_id"] == "qwen3-coder-30b-a3b-instruct"
    assert fp["defects4j_version"] == "2.0.1"
    assert fp["d4j_subset"] == "2.0"


def test_fingerprint_optionals_may_be_none():
    fp = env_fingerprint(model_id="x")
    # These can be None when the respective tool isn't installed or we're not in a repo.
    assert "defects4j_version" in fp
    assert "defects4j_commit_sha" in fp
    assert "java_version" in fp
    assert fp["model_id"] == "x"


def test_fingerprint_python_version_matches_runtime():
    import platform
    assert env_fingerprint(model_id="x")["python_version"] == platform.python_version()
