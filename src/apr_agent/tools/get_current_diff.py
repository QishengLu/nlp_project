"""get_current_diff — show the cumulative `git diff HEAD` of agent edits so far.

Lets the LLM check what it has actually changed across all prior `replace_block`
calls without re-reading every file. Especially useful after multiple edits or
when the agent suspects a previous edit broke something.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from apr_agent.tools.registry import Tool, ToolResult

_MAX_CHARS = 30_000


class GetCurrentDiffTool(Tool):
    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)

    @property
    def name(self) -> str:
        return "get_current_diff"

    @property
    def description(self) -> str:
        return (
            "Return the cumulative unified diff of every edit you have made so "
            "far (i.e. `git diff HEAD` of the bug checkout). Use this to "
            "review your changes before calling finish, or to check the "
            "current state after multiple replace_block calls."
        )

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    def invoke(self, arguments: dict) -> ToolResult:
        del arguments
        try:
            res = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=str(self.work_dir),
                capture_output=True, text=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            err = f"{type(e).__name__}: {e}"
            return ToolResult(
                output=f"ERROR getting diff: {err}",
                meta={"error": err},
                is_error=True,
            )
        diff = res.stdout or ""
        if not diff.strip():
            return ToolResult(
                output="(no edits made yet — agent has not modified any file)",
                meta={"empty": True, "chars": 0},
            )
        truncated = False
        if len(diff) > _MAX_CHARS:
            diff = diff[:_MAX_CHARS] + "\n... (diff truncated)"
            truncated = True
        return ToolResult(
            output=diff,
            meta={"chars": len(diff), "truncated": truncated},
        )
