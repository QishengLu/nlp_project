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
            return ToolResult(output="",
                              meta={"error": "path and non-empty old_code required"},
                              is_error=True)

        try:
            abs_path = resolve_in_sandbox(self.work_dir, path_arg)
        except PathEscapeError as e:
            return ToolResult(output="", meta={"error": str(e)}, is_error=True)

        rel = str(abs_path.relative_to(self.work_dir.resolve()).as_posix())
        if rel in self._protected:
            return ToolResult(
                output="",
                meta={"error": "path is a protected trigger test — editing forbidden",
                      "path": rel},
                is_error=True,
            )

        if not abs_path.exists():
            return ToolResult(output="", meta={"error": f"file not found: {rel}"},
                              is_error=True)
        if abs_path.is_dir():
            return ToolResult(output="", meta={"error": f"path is a directory: {rel}"},
                              is_error=True)

        content = abs_path.read_text(encoding="utf-8")
        count = content.count(old_code)
        if count == 0:
            return ToolResult(
                output="",
                meta={"error": "old_code not found — add more context or re-read the file",
                      "matches": 0, "path": rel},
                is_error=True,
            )
        if count > 1:
            return ToolResult(
                output="",
                meta={"error": f"old_code matches {count} places — include more context "
                               f"to make the match unique",
                      "matches": count, "path": rel},
                is_error=True,
            )

        new_content = content.replace(old_code, new_code, 1)
        abs_path.write_text(new_content, encoding="utf-8")

        return ToolResult(
            output=f"applied 1 replacement in {rel}",
            meta={"applied": True, "matches": 1, "path": rel,
                  "bytes_before": len(content), "bytes_after": len(new_content)},
        )
