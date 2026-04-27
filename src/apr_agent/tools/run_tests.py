"""run_tests tool — executes `defects4j test` inside the bug checkout.

Regression labels:
    Each invocation partitions the failing set against the baseline (the bug's
    trigger tests, captured at worker startup) so the LLM sees explicit
    `newly_failing` / `still_failing` / `now_passing` lists instead of a flat
    "currently failing" list. Catches accidental regressions early.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from apr_agent.defects4j.test import run_tests as d4j_run_tests
from apr_agent.tools.registry import Tool, ToolResult


class RunTestsTool(Tool):
    def __init__(
        self,
        work_dir: Path,
        default_timeout_s: float = 300.0,
        *,
        baseline_failing: Iterable[str] = (),
    ):
        self.work_dir = Path(work_dir)
        self._default_timeout_s = default_timeout_s
        # Frozen at construction. Callers (worker) seed this from
        # checkout.metadata.trigger_tests so we can label regression turn-by-turn.
        self._baseline: frozenset[str] = frozenset(baseline_failing)

    @property
    def name(self) -> str:
        return "run_tests"

    @property
    def description(self) -> str:
        return (
            "Run the Defects4J test suite for the current bug. Optionally narrow "
            "to a single test with test_filter='ClassName::methodName'. Output "
            "partitions failing tests into NEWLY_FAILING (regressions you "
            "introduced), STILL_FAILING (trigger tests not yet fixed), and "
            "NOW_PASSING (trigger tests your edits already fixed)."
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
            err = f"{type(e).__name__}: {e}"
            return ToolResult(output=f"ERROR running tests: {err}",
                              meta={"error": err}, is_error=True)

        currently = set(res.failing_tests)
        newly_failing = sorted(currently - self._baseline)
        still_failing = sorted(currently & self._baseline)
        now_passing = sorted(self._baseline - currently)

        meta = {
            "failing_count": len(res.failing_tests),
            "currently_failing": sorted(currently),
            "newly_failing": newly_failing,            # regressions
            "still_failing": still_failing,            # trigger tests not yet fixed
            "now_passing": now_passing,                # trigger tests fixed by edits so far
            "baseline_size": len(self._baseline),
            "timed_out": res.timed_out,
            "runtime_s": round(res.runtime_s, 2),
            "exit_code": res.returncode,
            "output_tail": res.output_tail,
        }

        # Human summary for the LLM message. Keep regression info up top so the
        # model sees it without scrolling through the test-runner stack.
        human_lines = [
            f"failing: {len(res.failing_tests)}  "
            f"runtime: {res.runtime_s:.1f}s  "
            f"timed_out: {res.timed_out}",
            "--- regression vs baseline ---",
            f"  newly_failing  ({len(newly_failing)}): "
            + (", ".join(newly_failing) if newly_failing else "(none — no regressions)"),
            f"  still_failing  ({len(still_failing)}): "
            + (", ".join(still_failing) if still_failing else "(none — all trigger tests pass)"),
            f"  now_passing    ({len(now_passing)}): "
            + (", ".join(now_passing) if now_passing else "(none yet)"),
            "--- output tail ---",
            res.output_tail,
        ]
        return ToolResult(
            output="\n".join(human_lines),
            meta=meta,
            is_error=res.timed_out or (res.returncode != 0 and not res.failing_tests),
        )
