"""replace_block — exact-string search/replace with 0-or-2+ match rejection.

Safety:
- Path must resolve within the sandbox.
- `protected_paths` is a hard deny-list — the caller seeds it from
  `defects4j export -p tests.trigger` output so the agent can't edit the
  tests that judge it. This is a semantic guard, not a regex on filename.
"""
from __future__ import annotations

from pathlib import Path

from apr_agent.tools._paths import PathEscapeError, resolve_in_sandbox
from apr_agent.tools.registry import Tool, ToolResult


class ReplaceBlockTool(Tool):
    def __init__(self, work_dir: Path, protected_paths: list[str] | None = None):
        """`protected_paths` is a set of project-relative paths the agent cannot
        edit (typically the bug's trigger tests)."""
        self.work_dir = Path(work_dir)
        self._protected: set[str] = {
            str(Path(p).as_posix()) for p in (protected_paths or [])
        }

    @property
    def name(self) -> str:
        return "replace_block"

    @property
    def description(self) -> str:
        return (
            "Replace an exact block of text in a file with a new block. The "
            "old_code must match exactly once — zero or multiple matches abort "
            "(use more context). Editing the bug's trigger test files is forbidden."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_code": {"type": "string"},
                "new_code": {"type": "string"},
            },
            "required": ["path", "old_code", "new_code"],
        }

    def invoke(self, arguments: dict) -> ToolResult:
        path_arg = arguments.get("path", "")
        old_code = arguments.get("old_code", "")
        new_code = arguments.get("new_code", "")

        if not path_arg or old_code == "":
            err = "path and non-empty old_code required"
            return ToolResult(output=f"ERROR: {err}", meta={"error": err},
                              is_error=True)

        try:
            abs_path = resolve_in_sandbox(self.work_dir, path_arg)
        except PathEscapeError as e:
            return ToolResult(output=f"ERROR: {e}", meta={"error": str(e)},
                              is_error=True)

        rel = str(abs_path.relative_to(self.work_dir.resolve()).as_posix())
        if rel in self._protected:
            err = "path is a protected trigger test — editing forbidden"
            return ToolResult(
                output=f"ERROR: {err} (path={rel})",
                meta={"error": err, "path": rel},
                is_error=True,
            )

        if not abs_path.exists():
            err = f"file not found: {rel}"
            return ToolResult(output=f"ERROR: {err}", meta={"error": err},
                              is_error=True)
        if abs_path.is_dir():
            err = f"path is a directory: {rel}"
            return ToolResult(output=f"ERROR: {err}", meta={"error": err},
                              is_error=True)

        content = abs_path.read_text(encoding="utf-8")
        count = content.count(old_code)
        if count == 0:
            err = ("old_code not found in file — re-read the file (whitespace, "
                   "indentation, or surrounding context likely don't match exactly), "
                   "then retry with old_code copied verbatim from read_file output")
            return ToolResult(
                output=f"ERROR: {err} (path={rel}, matches=0, "
                       f"old_code length={len(old_code)} chars)",
                meta={"error": err, "matches": 0, "path": rel},
                is_error=True,
            )
        if count > 1:
            err = (f"old_code matches {count} places — extend old_code with more "
                   f"unique surrounding context until it matches exactly once")
            return ToolResult(
                output=f"ERROR: {err} (path={rel}, matches={count})",
                meta={"error": err, "matches": count, "path": rel},
                is_error=True,
            )

        new_content = content.replace(old_code, new_code, 1)
        abs_path.write_text(new_content, encoding="utf-8")

        # Mini-diff so the LLM sees exactly what landed without re-reading the
        # file. Shows the changed block + 3 lines of context on each side.
        mini = _render_mini_diff(content, new_content, old_code, new_code, ctx=3)

        return ToolResult(
            output=f"applied 1 replacement in {rel}\n\n{mini}",
            meta={"applied": True, "matches": 1, "path": rel,
                  "bytes_before": len(content), "bytes_after": len(new_content)},
        )


def _render_mini_diff(
    old_content: str, new_content: str,
    old_code: str, new_code: str, *, ctx: int = 3,
) -> str:
    """Show before/after with line numbers around the edit. Cheap to read."""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()

    # Where the old_code block started in old_content.
    char_idx = old_content.find(old_code)
    if char_idx < 0:
        return "(mini-diff unavailable — match index not found)"
    old_start_line = old_content.count("\n", 0, char_idx) + 1
    old_block_n = max(1, old_code.count("\n") + (0 if old_code.endswith("\n") else 1))
    old_end_line = old_start_line + old_block_n - 1

    new_block_n = max(1, new_code.count("\n") + (0 if new_code.endswith("\n") else 1))
    new_end_line = old_start_line + new_block_n - 1

    pre_start = max(1, old_start_line - ctx)
    post_end_old = min(len(old_lines), old_end_line + ctx)
    post_end_new = min(len(new_lines), new_end_line + ctx)

    def _slice(lines, lo, hi):
        width = max(3, len(str(hi)))
        return "\n".join(f"{str(i).rjust(width)}| {lines[i - 1]}"
                         for i in range(lo, hi + 1) if 1 <= i <= len(lines))

    return (
        f"--- before (lines {pre_start}-{post_end_old}) ---\n"
        f"{_slice(old_lines, pre_start, post_end_old)}\n"
        f"--- after (lines {pre_start}-{post_end_new}) ---\n"
        f"{_slice(new_lines, pre_start, post_end_new)}"
    )
