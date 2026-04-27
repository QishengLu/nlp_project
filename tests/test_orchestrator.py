"""Orchestrator sequential loop + CLI wiring."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from apr_agent.orchestrator.controller import (
    WorkerOutcome,
    build_worker_payload,
    run_batch,
    spawn_worker,
)


def test_build_payload_is_pure():
    p = build_worker_payload(
        bug_id="Math-1", exp_id="e", data_root="data", scratch_root="s",
        model_cfg={"name": "fake"}, agent_cfg={"max_turns": 3}, dataset_cfg={},
    )
    assert p["bug_id"] == "Math-1"
    assert p["data_root"] == "data"
    assert p["verify"] is True


def test_run_batch_calls_worker_per_bug(monkeypatch, tmp_path: Path):
    calls: list[str] = []

    def fake_spawn(payload, *, overall_timeout_s):
        calls.append(payload["bug_id"])
        return WorkerOutcome(bug_id=payload["bug_id"], returncode=0,
                             duration_s=0.1, stderr_tail="")

    monkeypatch.setattr("apr_agent.orchestrator.controller.spawn_worker", fake_spawn)
    outcomes = run_batch(
        bugs=["Math-1", "Math-2", "Lang-1"],
        exp_id="e", data_root=tmp_path / "data", scratch_root=tmp_path / "s",
        model_cfg={}, agent_cfg={}, dataset_cfg={},
    )
    assert calls == ["Math-1", "Math-2", "Lang-1"]
    assert [o.returncode for o in outcomes] == [0, 0, 0]


def test_run_batch_parallel_runs_concurrently(monkeypatch, tmp_path: Path):
    """With concurrency>1, workers run in parallel — total wall time should be
    close to the longest single worker, not the sum."""
    import time as _time

    started: list[float] = []

    def fake_spawn(payload, *, overall_timeout_s):
        started.append(_time.time())
        # Sleep to simulate work — use a short delay so the test stays fast.
        _time.sleep(0.5)
        return WorkerOutcome(bug_id=payload["bug_id"], returncode=0,
                             duration_s=0.5, stderr_tail="")

    monkeypatch.setattr("apr_agent.orchestrator.controller.spawn_worker", fake_spawn)
    t0 = _time.time()
    outcomes = run_batch(
        bugs=["A-1", "A-2", "A-3", "A-4"],
        exp_id="e", data_root=tmp_path / "data", scratch_root=tmp_path / "s",
        model_cfg={}, agent_cfg={}, dataset_cfg={},
        concurrency=4,
    )
    elapsed = _time.time() - t0
    assert len(outcomes) == 4
    # Sequential would be ~2.0s; with 4-way parallel should be ~0.5-0.8s.
    assert elapsed < 1.5, f"expected parallel run, got {elapsed:.2f}s wall"
    # All 4 workers should have started within 0.2s of each other.
    assert max(started) - min(started) < 0.3, "workers didn't start concurrently"


def test_run_batch_propagates_timeout_failure(monkeypatch, tmp_path: Path):
    def fake_spawn(payload, *, overall_timeout_s):
        return WorkerOutcome(bug_id=payload["bug_id"], returncode=-1,
                             duration_s=overall_timeout_s, stderr_tail="timed out")

    monkeypatch.setattr("apr_agent.orchestrator.controller.spawn_worker", fake_spawn)
    outcomes = run_batch(bugs=["Math-1"], exp_id="e",
                         data_root=tmp_path / "data", scratch_root=tmp_path / "s",
                         model_cfg={}, agent_cfg={}, dataset_cfg={})
    assert outcomes[0].returncode == -1
    assert "timed out" in outcomes[0].stderr_tail


def test_spawn_worker_on_bad_json(tmp_path: Path, monkeypatch):
    """Confirms spawn_worker correctly surfaces exit 2 on malformed payload."""
    # Send a payload that's valid JSON but missing required fields → TypeError
    # inside worker entry, which becomes rc=2 via the argparse-like guard.
    outcome = spawn_worker({"nope": "this is not a valid payload shape"})
    # Worker returns 2 (malformed payload) because WorkerPayload(**{}) raises TypeError.
    assert outcome.returncode == 2


def test_cli_summary_empty_experiment(tmp_path: Path):
    """CLI `summary --exp-id nonexistent` returns totals=0 cleanly."""
    r = subprocess.run(
        [sys.executable, "-m", "apr_agent.cli", "summary",
         "--data-root", str(tmp_path / "data"),
         "--exp-id", "nope", "--json"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["total"] == 0
    assert data["fix_rate"] == 0.0


def test_cli_run_batch_requires_bugs(tmp_path: Path):
    """Empty bugs: in config → exit 2."""
    config = tmp_path / "bugs.yaml"
    config.write_text(yaml.safe_dump({
        "model": {}, "agent": {}, "dataset": {}, "bugs": [],
    }))
    r = subprocess.run(
        [sys.executable, "-m", "apr_agent.cli", "run-batch",
         "--config", str(config), "--exp-id", "x",
         "--data-root", str(tmp_path / "data"),
         "--scratch-root", str(tmp_path / "s")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
    assert "no bugs to run" in r.stderr
