"""Orchestrator — spawns one worker subprocess per bug, aggregates results.

This is the sequential skeleton. M4 adds AIMD concurrency on top without
changing the public shape: orchestrator always treats each worker as a
black-box subprocess and reads results back off disk, not stdout.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WorkerOutcome:
    bug_id: str
    returncode: int
    duration_s: float
    stderr_tail: str


def build_worker_payload(
    *,
    bug_id: str,
    exp_id: str,
    data_root: Path | str,
    scratch_root: Path | str,
    model_cfg: dict,
    agent_cfg: dict,
    dataset_cfg: dict,
    verify: bool = True,
) -> dict:
    return {
        "bug_id": bug_id,
        "exp_id": exp_id,
        "data_root": str(data_root),
        "scratch_root": str(scratch_root),
        "model": model_cfg,
        "agent": agent_cfg,
        "dataset": dataset_cfg,
        "verify": verify,
    }


def spawn_worker(payload: dict, *, overall_timeout_s: float = 1800.0) -> WorkerOutcome:
    """Run `python -m apr_agent.agent.worker` with payload on stdin."""
    started = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "apr_agent.agent.worker"],
            input=json.dumps(payload),
            capture_output=True, text=True,
            timeout=overall_timeout_s,
        )
        rc = proc.returncode
        stderr_tail = "\n".join(proc.stderr.splitlines()[-30:])
    except subprocess.TimeoutExpired as e:
        rc = -1
        stderr_tail = f"worker timed out after {overall_timeout_s}s: {e}"
    return WorkerOutcome(
        bug_id=str(payload.get("bug_id", "?")),
        returncode=rc,
        duration_s=round(time.time() - started, 2),
        stderr_tail=stderr_tail,
    )


def run_batch(
    *,
    bugs: list[str],
    exp_id: str,
    data_root: Path | str,
    scratch_root: Path | str,
    model_cfg: dict,
    agent_cfg: dict,
    dataset_cfg: dict,
    overall_timeout_s: float = 1800.0,
    verify: bool = True,
    on_outcome=None,                    # callable(WorkerOutcome) -> None
) -> list[WorkerOutcome]:
    """Run every bug in `bugs` sequentially. Returns a list of outcomes.

    Concurrency is out of scope for M3; plug in the RolloutRunner AIMD scheduler
    in M4 by batching spawn_worker calls via a pool instead of this loop.
    """
    outcomes: list[WorkerOutcome] = []
    for bug_id in bugs:
        payload = build_worker_payload(
            bug_id=bug_id, exp_id=exp_id,
            data_root=data_root, scratch_root=scratch_root,
            model_cfg=model_cfg, agent_cfg=agent_cfg,
            dataset_cfg=dataset_cfg, verify=verify,
        )
        outcome = spawn_worker(payload, overall_timeout_s=overall_timeout_s)
        outcomes.append(outcome)
        if on_outcome is not None:
            on_outcome(outcome)
    return outcomes
