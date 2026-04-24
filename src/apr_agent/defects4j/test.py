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


_FAIL_FILE_MARKERS = ("failing_tests",)


def run_tests(
    work_dir: Path,
    *,
    test_filter: str | None = None,
    timeout_s: float = 300.0,
    tail_lines: int = 200,
) -> TestResult:
    """Run `defects4j test` in work_dir, optionally filtered to a single test.

    Defects4J writes the list of currently failing tests to `failing_tests` in
    the project root. We parse that file as the authoritative source of truth
    (the stdout output is less reliable across project configurations).
    """
    args = ["test"]
    if test_filter:
        args += ["-t", test_filter]
    proc = run_defects4j(args, cwd=work_dir, timeout_s=timeout_s)

    failing = _read_failing_tests_file(work_dir)
    raw = proc.stdout + ("\n--STDERR--\n" + proc.stderr if proc.stderr else "")
    tail = "\n".join(raw.splitlines()[-tail_lines:])

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
    """Parse the Defects4J-generated `failing_tests` file (stable across projects)."""
    p = work_dir / "failing_tests"
    if not p.exists():
        return []
    out: list[str] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _FAIL_LINE_RE.match(line.strip())
        if m:
            out.append(f"{m.group(1)}::{m.group(2)}")
    # dedupe while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in out:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def current_failing(work_dir: Path, *, timeout_s: float = 300.0) -> list[str]:
    """Convenience: run full test suite, return failing list (ignores pass count)."""
    return run_tests(work_dir, timeout_s=timeout_s).failing_tests
