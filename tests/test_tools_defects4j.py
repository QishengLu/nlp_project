"""Unit tests for run_tests / get_failing_tests (mock the d4j runner)."""
from __future__ import annotations

from pathlib import Path

import pytest

from apr_agent.defects4j.test import TestResult
from apr_agent.tools.get_failing import GetFailingTestsTool
from apr_agent.tools.run_tests import RunTestsTool


def _fake_test_result(**overrides) -> TestResult:
    base = dict(
        returncode=0, timed_out=False, runtime_s=1.5,
        failing_tests=["org.FooTest::bar"], passing_tests=[],
        raw_output="all the log\nlast line",
        output_tail="last line",
    )
    base.update(overrides)
    return TestResult(**base)


def test_run_tests_happy_path(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "apr_agent.tools.run_tests.d4j_run_tests",
        lambda work_dir, test_filter=None, timeout_s=300.0: _fake_test_result(),
    )
    r = RunTestsTool(tmp_path).invoke({})
    assert r.meta["failing_count"] == 1
    assert r.meta["currently_failing"] == ["org.FooTest::bar"]
    assert r.meta["timed_out"] is False
    assert "last line" in r.output


def test_run_tests_labels_regression_against_baseline(tmp_path: Path, monkeypatch):
    """When the failing set diverges from baseline, output partitions newly /
    still / now-passing so the LLM sees the regression explicitly."""
    monkeypatch.setattr(
        "apr_agent.tools.run_tests.d4j_run_tests",
        lambda work_dir, test_filter=None, timeout_s=300.0: _fake_test_result(
            failing_tests=["org.FooTest::baz", "org.OtherTest::regression"],
        ),
    )
    tool = RunTestsTool(
        tmp_path,
        baseline_failing={"org.FooTest::bar", "org.FooTest::baz"},
    )
    r = tool.invoke({})
    assert r.meta["newly_failing"] == ["org.OtherTest::regression"]
    assert r.meta["still_failing"] == ["org.FooTest::baz"]
    assert r.meta["now_passing"] == ["org.FooTest::bar"]
    assert "newly_failing" in r.output and "regression" in r.output


def test_run_tests_no_baseline_means_everything_is_newly_failing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "apr_agent.tools.run_tests.d4j_run_tests",
        lambda work_dir, test_filter=None, timeout_s=300.0: _fake_test_result(),
    )
    r = RunTestsTool(tmp_path).invoke({})  # no baseline
    assert r.meta["newly_failing"] == ["org.FooTest::bar"]
    assert r.meta["still_failing"] == []
    assert r.meta["now_passing"] == []


def test_run_tests_propagates_timeout_filter(tmp_path: Path, monkeypatch):
    seen = {}

    def fake(work_dir, test_filter=None, timeout_s=300.0):
        seen["filter"] = test_filter
        seen["timeout"] = timeout_s
        return _fake_test_result(timed_out=True, failing_tests=[])

    monkeypatch.setattr("apr_agent.tools.run_tests.d4j_run_tests", fake)
    r = RunTestsTool(tmp_path).invoke({"test_filter": "org.FooTest::bar", "timeout_s": 60})
    assert seen == {"filter": "org.FooTest::bar", "timeout": 60.0}
    assert r.is_error is True  # timed_out → error


def test_run_tests_surfaces_subprocess_failure(tmp_path: Path, monkeypatch):
    def boom(*_a, **_kw):
        raise RuntimeError("defects4j checkout failed")

    monkeypatch.setattr("apr_agent.tools.run_tests.d4j_run_tests", boom)
    r = RunTestsTool(tmp_path).invoke({})
    assert r.is_error is True
    assert "RuntimeError" in r.meta["error"]


def test_get_failing_reads_cached_file(tmp_path: Path):
    (tmp_path / "failing_tests").write_text(
        "--- org.x.YTest::a\n--- org.x.YTest::b\n"
    )
    r = GetFailingTestsTool(tmp_path).invoke({})
    assert r.meta["source"] == "cached_file"
    assert r.output.splitlines() == ["org.x.YTest::a", "org.x.YTest::b"]


def test_get_failing_runs_defects4j_when_no_cache(tmp_path: Path, monkeypatch):
    called = {}

    def fake(work_dir, timeout_s=300.0):
        called["yes"] = True
        return _fake_test_result(failing_tests=["org.Z::zzz"])

    monkeypatch.setattr("apr_agent.tools.get_failing.d4j_run_tests", fake)
    r = GetFailingTestsTool(tmp_path).invoke({})
    assert called.get("yes") is True
    assert r.meta["source"] == "ran_defects4j_test"
    assert r.output == "org.Z::zzz"


# --- integration tests — skipped automatically when `defects4j` not on PATH ---

@pytest.mark.defects4j
@pytest.mark.slow
def test_real_defects4j_checkout_math(tmp_path: Path):
    from apr_agent.defects4j.checkout import checkout_bug, teardown
    co = checkout_bug("Math-2", scratch_root=tmp_path / "scratch")
    try:
        assert (co.work_dir / "src").exists()
        assert co.metadata.trigger_tests, "trigger_tests must be non-empty for Math-2"
        assert all("::" in t for t in co.metadata.trigger_tests)
    finally:
        teardown(co)


@pytest.mark.defects4j
@pytest.mark.slow
def test_real_defects4j_verify_fixed_version_passes(tmp_path: Path):
    """Check out the FIXED version, diff vs buggy, verify the diff -> all_passing."""
    import subprocess

    from apr_agent.defects4j.checkout import checkout_bug, git_init_baseline, teardown
    from apr_agent.defects4j.verify import verify_patch

    fixed = checkout_bug("Math-2", scratch_root=tmp_path / "scratch", version="f")
    try:
        buggy = checkout_bug("Math-2", scratch_root=tmp_path / "scratch-b", version="b")
        try:
            git_init_baseline(buggy.work_dir)
            # Overlay the fixed src over the buggy checkout, then diff.
            subprocess.run(
                ["rsync", "-a", "--delete",
                 f"{fixed.work_dir}/src/", f"{buggy.work_dir}/src/"],
                check=True,
            )
            from apr_agent.defects4j.checkout import diff_from_baseline
            patch = diff_from_baseline(buggy.work_dir)
            assert patch.strip(), "fix vs buggy diff should be non-empty"
            result = verify_patch("Math-2", patch,
                                  scratch_root=tmp_path / "scratch-v")
            assert result.patch_applied is True
            assert result.all_passing is True
        finally:
            teardown(buggy)
    finally:
        teardown(fixed)
