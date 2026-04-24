"""Collect an environment fingerprint for trajectory reproducibility.

Emits a dict suitable for `meta.env_fingerprint`. Design doc §12 lists the
required fields. Best-effort: missing tools degrade to None rather than raising.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from functools import lru_cache


def env_fingerprint(
    *,
    model_id: str,
    defects4j_version: str | None = None,
    d4j_subset: str | None = None,
    apr_agent_version: str | None = None,
) -> dict:
    return {
        "git_sha": _git_sha(),
        "defects4j_version": defects4j_version,
        "defects4j_commit_sha": _defects4j_commit_sha(),
        "d4j_subset": d4j_subset,
        "java_version": _java_version(),
        "tz": os.environ.get("TZ"),
        "python_version": platform.python_version(),
        "apr_agent_version": apr_agent_version or _apr_agent_version(),
        "model_id": model_id,
        "host": platform.node(),
    }


@lru_cache(maxsize=1)
def _git_sha() -> str | None:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=False)
        return res.stdout.strip() or None
    except FileNotFoundError:
        return None


@lru_cache(maxsize=1)
def _defects4j_commit_sha() -> str | None:
    """Read framework/../.git/HEAD of the installed defects4j checkout."""
    d4j = shutil.which("defects4j")
    if not d4j:
        return None
    try:
        from pathlib import Path
        # framework/bin/defects4j → framework/../
        repo = Path(d4j).resolve().parent.parent.parent
        res = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=False)
        return res.stdout.strip() or None
    except (OSError, FileNotFoundError):
        return None


@lru_cache(maxsize=1)
def _java_version() -> str | None:
    try:
        res = subprocess.run(["java", "-version"],
                             capture_output=True, text=True, check=False)
        # `java -version` writes to stderr. First line looks like:
        # openjdk version "1.8.0_392"
        line = (res.stderr or res.stdout).splitlines()[:1]
        if not line:
            return None
        return line[0].strip()
    except FileNotFoundError:
        return None


@lru_cache(maxsize=1)
def _apr_agent_version() -> str:
    try:
        from apr_agent import __version__
        return __version__
    except ImportError:
        return "unknown"
