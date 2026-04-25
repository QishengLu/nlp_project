"""Defects4J test runner + output parsing."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from apr_agent.defects4j.runner import run_defects4j


@dataclass
class TestResult:
    returncode: int
    timed_out: bool
    runtime_s: float
    failing_tests: list[str] = field(default_factory=list)
    passing_tests: list[str] = field(default_factory=list)   # only populated with -t filter
    raw_output: str = ""
    output_tail: str = ""


# Tell pytest this dataclass isn't a test class (otherwise its name triggers
# "Test*" discovery and produces a collection warning).
TestResult.__test__ = False


_FAIL_FILE_MARKERS = ("failing_tests",)


def run_tests(
    work_dir: Path,
    *,
    test_filter: str | None = None,
    timeout_s: float = 300.0,
    tail_lines: int = 200,
) -> TestResult:
    """Run `defects4j test` in work_dir, optionally filtered to a single test.

    Defects4J writes the list of currently failing tests (with assertion
    messages + stack traces) to a `failing_tests` file in the project root.
    We parse that as the authoritative source of truth and append the per-test
    failure detail to `output_tail` so the LLM sees exactly what assertion
    fired and where.
    """
    args = ["test"]
    if test_filter:
        args += ["-t", test_filter]
    proc = run_defects4j(args, cwd=work_dir, timeout_s=timeout_s)

    failing = _read_failing_tests_file(work_dir)
    details = read_failing_tests_with_details(work_dir)
    raw = proc.stdout + ("\n--STDERR--\n" + proc.stderr if proc.stderr else "")
    tail = "\n".join(raw.splitlines()[-tail_lines:])

    if details:
        detail_block = "\n\n--- failing test details ---\n" + "\n\n".join(
            f"### {tid}\n{detail}" for tid, detail in details.items()
        )
        tail = tail + detail_block

    return TestResult(
        returncode=proc.returncode,
        timed_out=proc.timed_out,
        runtime_s=proc.runtime_s,
        failing_tests=failing,
        raw_output=raw,
        output_tail=tail,
    )


_FAIL_LINE_RE = re.compile(r"---\s+([\w.$]+)::([\w$]+)")


def _read_failing_tests_file(work_dir: Path) -> list[str]:
    """Parse just the test names from `failing_tests`. Cheap; no detail."""
    p = work_dir / "failing_tests"
    if not p.exists():
        return []
    out: list[str] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _FAIL_LINE_RE.match(line.strip())
        if m:
            out.append(f"{m.group(1)}::{m.group(2)}")
    seen: set[str] = set()
    unique: list[str] = []
    for t in out:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def read_failing_tests_with_details(
    work_dir: Path, *, max_chars_per_test: int = 2000,
) -> dict[str, str]:
    """Parse `failing_tests` into {test_id: assertion+stack_trace}.

    Defects4J writes blocks like:
        --- org.foo.BarTest::baz
        java.lang.AssertionError: expected:<1> but was:<2>
            at org.junit.Assert.fail(Assert.java:91)
            at org.foo.BarTest.baz(BarTest.java:42)
        --- org.foo.BarTest::qux
        ...
    We capture everything between `--- name` markers as that test's detail block.
    """
    p = work_dir / "failing_tests"
    if not p.exists():
        return {}

    out: dict[str, str] = {}
    current_id: str | None = None
    buf: list[str] = []

    def _flush():
        if current_id is not None and current_id not in out:
            text = "\n".join(buf).rstrip()
            if len(text) > max_chars_per_test:
                text = text[:max_chars_per_test] + "\n... (truncated)"
            out[current_id] = text

    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _FAIL_LINE_RE.match(line.strip())
        if m:
            _flush()
            current_id = f"{m.group(1)}::{m.group(2)}"
            buf = []
        else:
            buf.append(line)
    _flush()
    return out


def current_failing(work_dir: Path, *, timeout_s: float = 300.0) -> list[str]:
    """Convenience: run full test suite, return failing list (ignores pass count)."""
    return run_tests(work_dir, timeout_s=timeout_s).failing_tests
