"""get_failing_tests tool — quick lookup of currently-failing tests.

Cheap path: if a `failing_tests` file exists from a prior `defects4j test`
invocation, parse it. If not, run `defects4j test` once to populate it.
"""
from __future__ import annotations

from pathlib import Path

from apr_agent.defects4j.test import _read_failing_tests_file, run_tests as d4j_run_tests
from apr_agent.tools.registry import Tool, ToolResult


class GetFailingTestsTool(Tool):
    def __init__(self, work_dir: Path, default_timeout_s: float = 300.0):
        self.work_dir = Path(work_dir)
        self._default_timeout_s = default_timeout_s

    @property
    def name(self) -> str:
        return "get_failing_tests"

    @property
    def description(self) -> str:
        return (
            "Return the list of tests currently failing in the bug checkout. "
            "Cheaper than run_tests when you just need the failing set — reads a "
            "cached `failing_tests` file if present, otherwise runs the suite once."
        )

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    def invoke(self, arguments: dict) -> ToolResult:
        del arguments
        cached = _read_failing_tests_file(self.work_dir)
        if cached:
            return ToolResult(
                output="\n".join(cached),
                meta={"count": len(cached), "source": "cached_file"},
            )
        try:
            res = d4j_run_tests(self.work_dir, timeout_s=self._default_timeout_s)
        except Exception as e:  # noqa: BLE001
            return ToolResult(output="", meta={"error": f"{type(e).__name__}: {e}"},
                              is_error=True)
        return ToolResult(
            output="\n".join(res.failing_tests),
            meta={"count": len(res.failing_tests), "source": "ran_defects4j_test",
                  "runtime_s": round(res.runtime_s, 2)},
        )
