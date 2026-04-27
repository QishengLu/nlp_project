"""search_code — ripgrep wrapper with a pure-Python fallback.

Prefers `rg` when a real binary is on PATH (fast, gitignore-aware). Falls back
to an in-process regex scan with hardcoded ignore dirs when rg is unavailable.
The fallback is intentionally small: literal or regex pattern, line-oriented
matches, same return shape as the rg path.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from apr_agent.tools._paths import PathEscapeError, resolve_in_sandbox
from apr_agent.tools.registry import Tool, ToolResult

_IGNORE_DIRS = {".git", ".svn", "__pycache__", "target", "build", ".venv", "node_modules"}
_TEXT_EXT_BLOCKLIST = {".class", ".jar", ".png", ".jpg", ".gif", ".pdf", ".zip"}


class SearchCodeTool(Tool):
    def __init__(self, work_dir: Path, rg_bin: str = "rg"):
        self.work_dir = Path(work_dir)
        self._rg_bin = rg_bin

    @property
    def name(self) -> str:
        return "search_code"

    @property
    def description(self) -> str:
        return (
            "Search source files under the bug checkout for a pattern and return "
            "a list of {file, line, content} hits. Set is_regex=true to treat the "
            "pattern as a regex; otherwise it's a fixed string."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "is_regex": {"type": "boolean", "default": False},
                "max_results": {"type": "integer", "default": 50, "minimum": 1},
            },
            "required": ["pattern"],
        }

    def invoke(self, arguments: dict) -> ToolResult:
        pattern = arguments.get("pattern", "")
        if not pattern:
            return ToolResult(output="ERROR: empty pattern",
                              meta={"error": "empty pattern"}, is_error=True)

        path_arg = arguments.get("path", ".") or "."
        is_regex = bool(arguments.get("is_regex", False))
        max_results = int(arguments.get("max_results", 50) or 50)

        try:
            abs_path = resolve_in_sandbox(self.work_dir, path_arg)
        except PathEscapeError as e:
            return ToolResult(output=f"ERROR: {e}", meta={"error": str(e)}, is_error=True)

        rg_path = _resolve_real_rg(self._rg_bin)
        if rg_path is not None:
            hits, backend = self._search_rg(rg_path, pattern, abs_path, is_regex, max_results)
        else:
            hits, backend = self._search_py(pattern, abs_path, is_regex, max_results)

        return ToolResult(
            output=json.dumps(hits, ensure_ascii=False),
            meta={"count": len(hits), "pattern": pattern, "is_regex": is_regex,
                  "truncated": len(hits) >= max_results, "backend": backend},
        )

    # --- ripgrep backend ---

    def _search_rg(self, rg_path: str, pattern: str, abs_path: Path,
                   is_regex: bool, max_results: int) -> tuple[list[dict], str]:
        cmd = [rg_path, "--json", "--no-heading", "--line-number", "--color=never"]
        if not is_regex:
            cmd.append("-F")
        cmd.extend(["-m", str(max_results), "--", pattern, str(abs_path)])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            return [], "rg-timeout"

        if proc.returncode == 2:
            # ripgrep error (e.g. invalid regex). Fall through with empty result.
            return [], "rg-error"

        hits: list[dict] = []
        root = self.work_dir.resolve()
        for line in proc.stdout.splitlines():
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") != "match":
                continue
            data = rec.get("data", {})
            file_path = data.get("path", {}).get("text", "")
            line_no = data.get("line_number")
            content = data.get("lines", {}).get("text", "").rstrip("\n")
            try:
                rel = str(Path(file_path).resolve().relative_to(root))
            except ValueError:
                rel = file_path
            hits.append({"file": rel, "line": line_no, "content": content})
            if len(hits) >= max_results:
                break
        return hits, "rg"

    # --- python backend ---

    def _search_py(self, pattern: str, abs_path: Path,
                   is_regex: bool, max_results: int) -> tuple[list[dict], str]:
        root = self.work_dir.resolve()
        hits: list[dict] = []
        try:
            if is_regex:
                regex = re.compile(pattern)
            else:
                regex = re.compile(re.escape(pattern))
        except re.error as e:
            return [{"_error": f"invalid regex: {e}"}], "py-error"

        candidates: list[Path]
        if abs_path.is_file():
            candidates = [abs_path]
        else:
            candidates = []
            for p in _iter_text_files(abs_path):
                candidates.append(p)

        for f in candidates:
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, start=1):
                        if regex.search(line):
                            try:
                                rel = str(f.resolve().relative_to(root))
                            except ValueError:
                                rel = str(f)
                            hits.append({"file": rel, "line": i,
                                         "content": line.rstrip("\n")})
                            if len(hits) >= max_results:
                                return hits, "py"
            except OSError:
                continue
        return hits, "py"


def _iter_text_files(root: Path):
    """Yield candidate text files under root, skipping ignored dirs + binaries."""
    import os
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS]
        for fn in filenames:
            if any(fn.endswith(ext) for ext in _TEXT_EXT_BLOCKLIST):
                continue
            yield Path(dirpath) / fn


def _resolve_real_rg(rg_bin: str) -> str | None:
    """Resolve `rg_bin` to an actual executable path.

    `shutil.which` may return a shell-function-wrapped `rg` (Claude Code's CLI
    replays it as itself). We verify the resolved path is an ELF/Mach-O file,
    not a shell function, by checking it exists as a regular file and is
    executable.
    """
    found = shutil.which(rg_bin)
    if not found:
        return None
    p = Path(found)
    if not p.is_file():
        return None
    return found
