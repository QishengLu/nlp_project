"""run_tests tool — executes `defects4j test` inside the bug checkout."""
from __future__ import annotations

from pathlib import Path

from apr_agent.defects4j.test import run_tests as d4j_run_tests
from apr_agent.tools.registry import Tool, ToolResult


class RunTestsTool(Tool):
    def __init__(self, work_dir: Path, default_timeout_s: float = 300.0):
        self.work_dir = Path(work_dir)
        self._default_timeout_s = default_timeout_s

    @property
    def name(self) -> str:
        return "run_tests"

    @property
    def description(self) -> str:
        return (
            "Run the Defects4J test suite for the current bug. Optionally narrow "
            "to a single test with test_filter='ClassName::methodName'. Returns "
            "a summary with failing tests and the tail of the output."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "test_filter": {
                    "type": "string",
                    "description": "Optional single-test filter, e.g. 'org.FooTest::bar'.",
                },
                "timeout_s": {"type": "integer", "default": 300, "minimum": 10},
            },
        }

    def invoke(self, arguments: dict) -> ToolResult:
        test_filter = arguments.get("test_filter") or None
        timeout_s = float(arguments.get("timeout_s") or self._default_timeout_s)

        try:
            res = d4j_run_tests(
                self.work_dir, test_filter=test_filter, timeout_s=timeout_s,
            )
        except Exception as e:  # noqa: BLE001 — surface any subprocess failure to the LLM
            return ToolResult(output="",
                              meta={"error": f"{type(e).__name__}: {e}"},
                              is_error=True)

        summary = {
            "failing_count": len(res.failing_tests),
            "failing_tests": res.failing_tests[:50],
            "timed_out": res.timed_out,
            "runtime_s": round(res.runtime_s, 2),
            "exit_code": res.returncode,
        }
        human = (
            f"failing: {len(res.failing_tests)}  "
            f"runtime: {res.runtime_s:.1f}s  "
            f"timed_out: {res.timed_out}\n"
            f"--- output tail ---\n{res.output_tail}"
        )
        return ToolResult(
            output=human,
            meta={**summary, "output_tail": res.output_tail},
            is_error=res.timed_out or (res.returncode != 0 and not res.failing_tests),
        )
