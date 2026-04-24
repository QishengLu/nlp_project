"""Tests for read_file / list_directory / search_code / replace_block."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from apr_agent.tools.list_directory import ListDirectoryTool
from apr_agent.tools.read_file import ReadFileTool
from apr_agent.tools.replace_block import ReplaceBlockTool
from apr_agent.tools.search_code import SearchCodeTool


@pytest.fixture()
def work(tmp_path: Path) -> Path:
    (tmp_path / "src/main/java/pkg").mkdir(parents=True)
    (tmp_path / "src/main/java/pkg/Foo.java").write_text(
        "public class Foo {\n"
        "    public int add(int a, int b) {\n"
        "        return a - b;\n"   # the bug
        "    }\n"
        "}\n"
    )
    (tmp_path / "src/test/java/pkg").mkdir(parents=True)
    (tmp_path / "src/test/java/pkg/FooTest.java").write_text(
        "public class FooTest { /* trigger test */ }\n"
    )
    (tmp_path / "README.md").write_text("# demo\n")
    return tmp_path


# -------- read_file --------

def test_read_file_numbered(work: Path):
    r = ReadFileTool(work).invoke({"path": "src/main/java/pkg/Foo.java"})
    assert r.is_error is False
    assert " 1  public class Foo {" in r.output
    assert r.meta["total_lines"] == 5


def test_read_file_range(work: Path):
    r = ReadFileTool(work).invoke(
        {"path": "src/main/java/pkg/Foo.java", "start_line": 2, "end_line": 3}
    )
    assert r.is_error is False
    assert r.output.splitlines() == [
        " 2      public int add(int a, int b) {",
        " 3          return a - b;",
    ]


def test_read_file_not_found(work: Path):
    r = ReadFileTool(work).invoke({"path": "does/not/exist.java"})
    assert r.is_error is True
    assert "not found" in r.meta["error"]


def test_read_file_path_escape_blocked(work: Path):
    r = ReadFileTool(work).invoke({"path": "../../etc/passwd"})
    assert r.is_error is True
    assert "escapes sandbox" in r.meta["error"]


def test_read_file_directory_rejected(work: Path):
    r = ReadFileTool(work).invoke({"path": "src"})
    assert r.is_error is True


# -------- list_directory --------

def test_list_shallow(work: Path):
    r = ListDirectoryTool(work).invoke({"path": "."})
    assert r.is_error is False
    entries = r.output.splitlines()
    assert "src/" in entries
    assert "README.md" in entries


def test_list_recursive(work: Path):
    r = ListDirectoryTool(work).invoke({"path": ".", "recursive": True})
    assert r.is_error is False
    assert "src/main/java/pkg/Foo.java" in r.output


def test_list_max_entries_truncates(work: Path):
    r = ListDirectoryTool(work).invoke({"path": ".", "recursive": True, "max_entries": 2})
    assert len(r.output.splitlines()) <= 2
    assert r.meta["truncated"] is True


def test_list_ignores_build_dirs(work: Path):
    (work / "target/classes").mkdir(parents=True)
    (work / "target/classes/Foo.class").write_text("x")
    r = ListDirectoryTool(work).invoke({"path": ".", "recursive": True})
    assert "target/" not in r.output
    assert "Foo.class" not in r.output


# -------- search_code --------

def test_search_code_fixed_string(work: Path):
    r = SearchCodeTool(work).invoke({"pattern": "a - b"})
    assert r.is_error is False
    hits = json.loads(r.output)
    assert any(h["file"].endswith("Foo.java") and h["line"] == 3 for h in hits)


def test_search_code_regex(work: Path):
    r = SearchCodeTool(work).invoke(
        {"pattern": r"public\s+class\s+\w+", "is_regex": True}
    )
    assert r.is_error is False
    hits = json.loads(r.output)
    assert len(hits) >= 1


def test_search_code_no_match(work: Path):
    r = SearchCodeTool(work).invoke({"pattern": "no-such-string-anywhere-xyz-123"})
    assert r.is_error is False
    assert json.loads(r.output) == []


# -------- replace_block --------

def test_replace_block_unique_match(work: Path):
    tool = ReplaceBlockTool(work)
    r = tool.invoke({
        "path": "src/main/java/pkg/Foo.java",
        "old_code": "return a - b;",
        "new_code": "return a + b;",
    })
    assert r.is_error is False
    assert r.meta["applied"] is True
    assert (work / "src/main/java/pkg/Foo.java").read_text().count("a + b") == 1


def test_replace_block_no_match(work: Path):
    tool = ReplaceBlockTool(work)
    r = tool.invoke({
        "path": "src/main/java/pkg/Foo.java",
        "old_code": "not present",
        "new_code": "x",
    })
    assert r.is_error is True
    assert r.meta["matches"] == 0


def test_replace_block_multi_match_rejected(work: Path):
    p = work / "src/main/java/pkg/Foo.java"
    p.write_text("x = 1;\nx = 1;\n")
    tool = ReplaceBlockTool(work)
    r = tool.invoke({
        "path": "src/main/java/pkg/Foo.java",
        "old_code": "x = 1;",
        "new_code": "x = 2;",
    })
    assert r.is_error is True
    assert r.meta["matches"] == 2


def test_replace_block_trigger_test_denied(work: Path):
    tool = ReplaceBlockTool(
        work,
        protected_paths=["src/test/java/pkg/FooTest.java"],
    )
    r = tool.invoke({
        "path": "src/test/java/pkg/FooTest.java",
        "old_code": "trigger test",
        "new_code": "gutted",
    })
    assert r.is_error is True
    assert "protected" in r.meta["error"]
    # File must be unchanged.
    assert "trigger test" in (work / "src/test/java/pkg/FooTest.java").read_text()


def test_replace_block_sandbox_escape(work: Path):
    r = ReplaceBlockTool(work).invoke({
        "path": "../outside.txt",
        "old_code": "x",
        "new_code": "y",
    })
    assert r.is_error is True
    assert "escapes sandbox" in r.meta["error"]
