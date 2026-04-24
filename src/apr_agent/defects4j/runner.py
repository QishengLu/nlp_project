"""Low-level subprocess wrapper around the `defects4j` CLI.

Design notes:
- Defects4J tests are TZ-sensitive (America/Los_Angeles). Every invocation
  hard-sets TZ in the child env. Workers that run outside this layer must
  also set TZ before they spawn their first `defects4j` subprocess.
- `defects4j` spawns JVM children. We put each invocation in its own process
  group via `start_new_session=True` so timeout kills propagate to the JVM too.
- stdout/stderr are captured in full. Raw bytes are returned; callers decide
  how much to keep in the trajectory (usually truncated tails).
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path


class Defects4jNotInstalled(RuntimeError):
    """Raised when `defects4j` is not on PATH."""


def defects4j_on_path() -> bool:
    return shutil.which("defects4j") is not None


def require_defects4j() -> str:
    found = shutil.which("defects4j")
    if found is None:
        raise Defects4jNotInstalled(
            "`defects4j` is not on PATH. Clone rjust/defects4j, run ./init.sh, "
            "and prepend framework/bin to PATH."
        )
    return found


@dataclass
class ProcResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    runtime_s: float


def run_defects4j(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout_s: float = 300.0,
    extra_env: dict[str, str] | None = None,
) -> ProcResult:
    """Invoke `defects4j <args>`, kill the whole process group on timeout."""
    import time
    require_defects4j()

    env = dict(os.environ)
    env["TZ"] = "America/Los_Angeles"
    if extra_env:
        env.update(extra_env)

    started = time.time()
    proc = subprocess.Popen(
        ["defects4j", *args],
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,  # new pgid so killpg hits the JVM children too
        text=True,
    )
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = proc.communicate()

    elapsed = time.time() - started
    return ProcResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=out or "",
        stderr=err or "",
        timed_out=timed_out,
        runtime_s=elapsed,
    )
