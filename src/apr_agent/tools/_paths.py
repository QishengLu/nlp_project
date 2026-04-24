"""Path resolution + sandbox guard shared by filesystem tools.

Tools run inside a per-bug checkout. The LLM must not escape that directory
(`../../etc/passwd`, absolute paths, symlinks to /tmp, etc.).
"""
from __future__ import annotations

from pathlib import Path


class PathEscapeError(ValueError):
    """Raised when a tool argument resolves outside the sandboxed work_dir."""


def resolve_in_sandbox(work_dir: Path, user_path: str) -> Path:
    """Resolve `user_path` under `work_dir` and reject anything that escapes.

    The check uses fully resolved (symlink-followed) absolute paths, so a
    symlink inside work_dir pointing out is also caught.
    """
    root = work_dir.resolve()
    # Strip leading slashes so "/src/Foo.java" is treated as relative.
    candidate_rel = user_path.lstrip("/")
    candidate = (root / candidate_rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as e:
        raise PathEscapeError(
            f"Path escapes sandbox: user_path={user_path!r} resolved to "
            f"{candidate} which is not under {root}"
        ) from e
    return candidate
