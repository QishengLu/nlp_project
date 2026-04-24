"""Defects4J metadata queries — trigger_tests, source dirs, modified classes."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from apr_agent.defects4j.runner import run_defects4j


@dataclass
class BugMetadata:
    """Per-bug metadata extracted from `defects4j export -p ...`."""
    trigger_tests: list[str]            # e.g. "org.Foo::testBar"
    relevant_tests: list[str]           # broader set
    modified_classes: list[str]
    source_dir: str                     # project-relative, e.g. "src/main/java"
    test_dir: str                       # project-relative, e.g. "src/test/java"
    dir_src_classes: str                # absolute or relative bin path
    dir_src_tests: str


_BUG_ID_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)-(\d+)$")


def parse_bug_id(bug_id: str) -> tuple[str, int]:
    m = _BUG_ID_RE.match(bug_id)
    if not m:
        raise ValueError(f"unrecognized bug id: {bug_id!r} (expected e.g. 'Math-12')")
    return m.group(1), int(m.group(2))


def export_property(work_dir: Path, prop: str, timeout_s: float = 60.0) -> str:
    """Run `defects4j export -p <prop>` inside a checked-out work_dir."""
    res = run_defects4j(["export", "-p", prop], cwd=work_dir, timeout_s=timeout_s)
    if res.returncode != 0:
        raise RuntimeError(
            f"defects4j export -p {prop} failed (rc={res.returncode}): {res.stderr[-500:]}"
        )
    return res.stdout.strip()


def get_bug_metadata(work_dir: Path) -> BugMetadata:
    """Query metadata for a bug whose buggy version has been checked out to work_dir."""
    triggers = _split_lines(export_property(work_dir, "tests.trigger"))
    relevant = _split_lines(export_property(work_dir, "tests.relevant"))
    modified = _split_lines(export_property(work_dir, "classes.modified"))
    source_dir = export_property(work_dir, "dir.src.classes")
    test_dir = export_property(work_dir, "dir.src.tests")
    return BugMetadata(
        trigger_tests=triggers,
        relevant_tests=relevant,
        modified_classes=modified,
        source_dir=source_dir,
        test_dir=test_dir,
        dir_src_classes=source_dir,
        dir_src_tests=test_dir,
    )


def _split_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def trigger_test_files(meta: BugMetadata) -> list[str]:
    """Translate 'org.apache.commons.math.TestFoo::bar' -> 'src/test/java/org/.../TestFoo.java'.

    Best-effort: the test dir and class-to-path mapping assumes Maven-style
    `src/test/java/<pkg>/<Class>.java`. Callers should treat the output as an
    advisory deny-list; the authoritative source is the raw trigger list.
    """
    out: list[str] = []
    for t in meta.trigger_tests:
        cls = t.split("::", 1)[0]
        rel = cls.replace(".", "/") + ".java"
        out.append(f"{meta.test_dir}/{rel}")
    return out
