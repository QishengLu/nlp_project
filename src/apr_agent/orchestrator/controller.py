"""Orchestrator — spawns one worker subprocess per bug, aggregates results.

Concurrency: ThreadPoolExecutor over `spawn_worker`. Each worker is its own
OS subprocess (with its own JVM tree under D4J), so threads here are just for
coordinating I/O — the real parallelism is at the process level. Each bug's
checkout dir is UUID-suffixed so concurrent D4J operations don't collide.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    concurrency: int = 1,
    on_outcome=None,                    # callable(WorkerOutcome) -> None
) -> list[WorkerOutcome]:
    """Run every bug in `bugs`. Returns outcomes in completion order (when
    concurrency>1) or input order (when concurrency==1).

    `concurrency` caps simultaneous workers. Each worker is its own subprocess
    (with its own JVM tree); 5 in parallel uses ~5-10GB RAM on Defects4J Math.
    `on_outcome(outcome)` fires as each worker completes — useful for live logs.
    """
    payloads = [
        build_worker_payload(
            bug_id=bug_id, exp_id=exp_id,
            data_root=data_root, scratch_root=scratch_root,
            model_cfg=model_cfg, agent_cfg=agent_cfg,
            dataset_cfg=dataset_cfg, verify=verify,
        )
        for bug_id in bugs
    ]

    outcomes: list[WorkerOutcome] = []

    if concurrency <= 1:
        for p in payloads:
            outcome = spawn_worker(p, overall_timeout_s=overall_timeout_s)
            outcomes.append(outcome)
            if on_outcome is not None:
                on_outcome(outcome)
        return outcomes

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = {
            ex.submit(spawn_worker, p, overall_timeout_s=overall_timeout_s): p
            for p in payloads
        }
        for future in as_completed(futures):
            outcome = future.result()
            outcomes.append(outcome)
            if on_outcome is not None:
                on_outcome(outcome)
    return outcomes
