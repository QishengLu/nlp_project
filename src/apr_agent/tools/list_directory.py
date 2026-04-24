"""list_directory — shallow or recursive directory listing within the sandbox."""
from __future__ import annotations

from pathlib import Path

from apr_agent.tools._paths import PathEscapeError, resolve_in_sandbox
from apr_agent.tools.registry import Tool, ToolResult

_IGNORE_DIRS = {".git", ".svn", "__pycache__", "target", "build", ".venv", "node_modules"}


class ListDirectoryTool(Tool):
    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)

    @property
    def name(self) -> str:
        return "list_directory"

    @property
    def description(self) -> str:
        return (
            "List directory entries under the bug checkout. Set recursive=true to "
            "walk the tree (skips .git/build/target). max_entries truncates output."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."},
                "recursive": {"type": "boolean", "default": False},
                "max_entries": {"type": "integer", "default": 200, "minimum": 1},
            },
        }

    def invoke(self, arguments: dict) -> ToolResult:
        path_arg = arguments.get("path", ".") or "."
        recursive = bool(arguments.get("recursive", False))
        max_entries = int(arguments.get("max_entries", 200) or 200)

        try:
            abs_path = resolve_in_sandbox(self.work_dir, path_arg)
        except PathEscapeError as e:
            return ToolResult(output="", meta={"error": str(e)}, is_error=True)

        if not abs_path.exists():
            return ToolResult(output="", meta={"error": f"path not found: {path_arg}"},
                              is_error=True)
        if not abs_path.is_dir():
            return ToolResult(output="", meta={"error": f"not a directory: {path_arg}"},
                              is_error=True)

        root = self.work_dir.resolve()
        entries: list[str] = []
        truncated = False

        if recursive:
            for dirpath, dirnames, filenames in _walk(abs_path, _IGNORE_DIRS):
                rel_dir = Path(dirpath).relative_to(root)
                for name in sorted(dirnames):
                    entries.append(f"{rel_dir / name}/")
                    if len(entries) >= max_entries:
                        truncated = True
                        break
                if truncated:
                    break
                for name in sorted(filenames):
                    entries.append(str(rel_dir / name))
                    if len(entries) >= max_entries:
                        truncated = True
                        break
                if truncated:
                    break
        else:
            children = sorted(abs_path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
            for p in children:
                rel = p.relative_to(root)
                entries.append(f"{rel}/" if p.is_dir() else str(rel))
                if len(entries) >= max_entries:
                    truncated = True
                    break

        output = "\n".join(entries)
        return ToolResult(
            output=output,
            meta={"count": len(entries), "truncated": truncated,
                  "recursive": recursive,
                  "path": str(abs_path.relative_to(root)) or "."},
        )


def _walk(root: Path, ignore_dirs: set[str]):
    """os.walk with in-place pruning of ignored dirs."""
    import os
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
        yield dirpath, dirnames, filenames
