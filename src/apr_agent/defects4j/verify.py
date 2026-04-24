"""Independent verify: fresh checkout + apply agent patch + test.

Deliberately does NOT reuse the agent's own scratch dir. The agent might have
left the JVM in a weird state, deleted files, or edited build configs. Verify
must be fully reproducible from (bug_id, patch) alone.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from apr_agent.defects4j.checkout import checkout_bug, teardown
from apr_agent.defects4j.test import run_tests as d4j_run_tests
from apr_agent.schema import VerifyResult


def verify_patch(
    bug_id: str,
    patch: str,
    *,
    scratch_root: Path,
    test_timeout_s: float = 300.0,
    keep_checkout: bool = False,
) -> VerifyResult:
    """Fresh checkout, apply patch, run defects4j test, return a VerifyResult.

    Success criteria:
    - patch applies cleanly (else patch_applied=False, all_passing=False)
    - all trigger tests pass
    - no previously-passing test regresses
    """
    co = checkout_bug(bug_id, scratch_root=scratch_root)
    try:
        trigger_tests = list(co.metadata.trigger_tests)

        if not patch.strip():
            return VerifyResult(
                all_passing=False,
                previously_failing_now_passing=[],
                newly_failing=trigger_tests,
                patch_applied=False,
                test_exit_code=-1,
                runtime_s=0.0,
                raw_output="empty patch",
            )

        applied = _apply_patch(co.work_dir, patch)
        if not applied:
            return VerifyResult(
                all_passing=False,
                previously_failing_now_passing=[],
                newly_failing=trigger_tests,
                patch_applied=False,
                test_exit_code=-2,
                runtime_s=0.0,
                raw_output="patch failed to apply",
            )

        res = d4j_run_tests(co.work_dir, timeout_s=test_timeout_s)
        failing_set = set(res.failing_tests)
        trigger_set = set(trigger_tests)

        newly_failing = sorted(failing_set - trigger_set)
        previously_failing_now_passing = sorted(trigger_set - failing_set)
        all_passing = not failing_set

        return VerifyResult(
            all_passing=all_passing,
            previously_failing_now_passing=previously_failing_now_passing,
            newly_failing=newly_failing,
            patch_applied=True,
            test_exit_code=res.returncode,
            runtime_s=round(res.runtime_s, 2),
            raw_output=res.output_tail,
        )
    finally:
        if not keep_checkout:
            teardown(co)


def _apply_patch(work_dir: Path, patch: str) -> bool:
    """Apply a unified diff produced by `git diff HEAD`. Returns True on success."""
    # `git apply --3way` tolerates the HEAD-relative paths git diff emits.
    res = subprocess.run(
        ["git", "apply", "--reject", "--whitespace=nowarn", "-"],
        cwd=work_dir, input=patch, text=True,
        capture_output=True,
    )
    if res.returncode == 0:
        return True
    # Fallback: `patch -p1` (some agents emit non-git diffs).
    res2 = subprocess.run(
        ["patch", "-p1", "--no-backup-if-mismatch", "--silent", "-f"],
        cwd=work_dir, input=patch, text=True, capture_output=True,
    )
    return res2.returncode == 0
