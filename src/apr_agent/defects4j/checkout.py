"""Defects4J checkout + teardown."""
from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from apr_agent.defects4j.info import BugMetadata, get_bug_metadata, parse_bug_id
from apr_agent.defects4j.runner import ProcResult, run_defects4j


@dataclass
class CheckedOut:
    work_dir: Path
    bug_id: str
    project: str
    bug_number: int
    metadata: BugMetadata


def checkout_bug(
    bug_id: str,
    *,
    scratch_root: Path,
    version: str = "b",     # "b" = buggy; "f" = fixed
    timeout_s: float = 180.0,
) -> CheckedOut:
    """Run `defects4j checkout -p <Project> -v <N><b|f> -w <dir>` and return metadata.

    Each checkout gets its own UUID-suffixed scratch dir so parallel workers
    never collide.
    """
    project, bug_number = parse_bug_id(bug_id)
    scratch_root = Path(scratch_root)
    scratch_root.mkdir(parents=True, exist_ok=True)
    work_dir = scratch_root / f"{bug_id}-{uuid.uuid4().hex[:8]}"

    res: ProcResult = run_defects4j(
        ["checkout", "-p", project, "-v", f"{bug_number}{version}", "-w", str(work_dir)],
        timeout_s=timeout_s,
    )
    if res.returncode != 0 or not work_dir.exists():
        raise RuntimeError(
            f"defects4j checkout {bug_id} failed (rc={res.returncode}): "
            f"{res.stderr[-500:]}"
        )

    metadata = get_bug_metadata(work_dir)
    return CheckedOut(
        work_dir=work_dir, bug_id=bug_id,
        project=project, bug_number=bug_number,
        metadata=metadata,
    )


def teardown(checkout: CheckedOut) -> None:
    """Delete the checkout's scratch dir. Safe to call twice."""
    if checkout.work_dir.exists():
        shutil.rmtree(checkout.work_dir, ignore_errors=True)


def git_init_baseline(work_dir: Path) -> None:
    """Ensure work_dir has a clean git baseline so agent edits can be diffed.

    Defects4J's own checkout already initializes a git repo with the buggy
    version committed (HEAD detached at D4J_<Project>_<N>_BUGGY_VERSION). In
    that case we use HEAD as the baseline — no extra commit needed. Only if
    no git repo exists (e.g. a non-D4J caller of this helper) do we init one.
    """
    import subprocess
    if (work_dir / ".git").is_dir():
        return
    subprocess.run(["git", "init", "-q"], cwd=work_dir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=work_dir, check=True)
    subprocess.run(
        ["git", "-c", "user.email=apr@agent.local", "-c", "user.name=apr-agent",
         "commit", "-qm", "base"],
        cwd=work_dir, check=True,
    )


def diff_from_baseline(work_dir: Path) -> str:
    """Unified diff of current tree vs the baseline commit created by git_init_baseline."""
    import subprocess
    res = subprocess.run(
        ["git", "diff", "HEAD"], cwd=work_dir,
        capture_output=True, text=True, check=False,
    )
    return res.stdout
