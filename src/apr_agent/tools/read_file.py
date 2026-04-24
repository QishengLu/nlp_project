"""read_file — show numbered lines of a text file under the bug checkout."""
from __future__ import annotations

from pathlib import Path

from apr_agent.tools._paths import PathEscapeError, resolve_in_sandbox
from apr_agent.tools.registry import Tool, ToolResult

_MAX_BYTES = 200_000  # refuse to read absurdly large files whole-hog


class ReadFileTool(Tool):
    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read a text file from the bug checkout and return its contents with "
            "line numbers. Use start_line/end_line to page through large files. "
            "end_line=-1 means 'to end of file'."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "Path relative to the bug checkout root."},
                "start_line": {"type": "integer", "default": 1, "minimum": 1},
                "end_line": {"type": "integer", "default": -1,
                             "description": "1-based inclusive; -1 means EOF."},
            },
            "required": ["path"],
        }

    def invoke(self, arguments: dict) -> ToolResult:
        path_arg = arguments.get("path", "")
        start_line = int(arguments.get("start_line", 1) or 1)
        end_line = int(arguments.get("end_line", -1) or -1)

        try:
            abs_path = resolve_in_sandbox(self.work_dir, path_arg)
        except PathEscapeError as e:
            return ToolResult(output="", meta={"error": str(e)}, is_error=True)

        if not abs_path.exists():
            return ToolResult(output="", meta={"error": f"file not found: {path_arg}"},
                              is_error=True)
        if abs_path.is_dir():
            return ToolResult(output="",
                              meta={"error": f"path is a directory: {path_arg}"},
                              is_error=True)

        size = abs_path.stat().st_size
        if size > _MAX_BYTES:
            return ToolResult(
                output="",
                meta={"error": f"file too large: {size} bytes > {_MAX_BYTES}",
                      "size": size},
                is_error=True,
            )

        try:
            raw = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ToolResult(output="", meta={"error": str(e)}, is_error=True)

        lines = raw.splitlines()
        total = len(lines)
        if start_line < 1:
            start_line = 1
        if end_line == -1 or end_line > total:
            end_line = total
        if start_line > total:
            return ToolResult(
                output="",
                meta={"error": f"start_line {start_line} past EOF (file has {total} lines)",
                      "total_lines": total},
                is_error=True,
            )

        width = max(2, len(str(end_line)))
        rendered = "\n".join(
            f"{str(i).rjust(width)}  {lines[i - 1]}"
            for i in range(start_line, end_line + 1)
        )
        return ToolResult(
            output=rendered,
            meta={"path": str(abs_path.relative_to(self.work_dir.resolve())),
                  "total_lines": total,
                  "start_line": start_line, "end_line": end_line},
        )
