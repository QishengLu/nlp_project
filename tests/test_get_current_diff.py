"""Tests for GetCurrentDiffTool — runs `git diff HEAD` in the bug checkout."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from apr_agent.tools.get_current_diff import GetCurrentDiffTool


def _git_init(work: Path):
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "add", "-A"], cwd=work, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "base"], cwd=work, check=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "Foo.java").write_text("class Foo { int x = 1; }\n")
    _git_init(tmp_path)
    return tmp_path


def test_get_current_diff_empty_when_no_edits(repo: Path):
    r = GetCurrentDiffTool(repo).invoke({})
    assert r.is_error is False
    assert r.meta["empty"] is True
    assert "no edits made yet" in r.output


def test_get_current_diff_shows_unified_diff(repo: Path):
    (repo / "Foo.java").write_text("class Foo { int x = 2; }\n")
    r = GetCurrentDiffTool(repo).invoke({})
    assert r.is_error is False
    assert r.meta.get("empty") is not True
    # unified diff hallmarks
    assert "diff --git" in r.output
    assert "-class Foo { int x = 1; }" in r.output
    assert "+class Foo { int x = 2; }" in r.output


def test_get_current_diff_truncates_huge_diffs(repo: Path, monkeypatch):
    # Force a small cap to exercise truncation without producing a huge file.
    import apr_agent.tools.get_current_diff as mod
    monkeypatch.setattr(mod, "_MAX_CHARS", 100)
    (repo / "Foo.java").write_text("class Foo {\n" + "  int x;\n" * 200 + "}\n")
    r = GetCurrentDiffTool(repo).invoke({})
    assert r.meta["truncated"] is True
    assert "(diff truncated)" in r.output
