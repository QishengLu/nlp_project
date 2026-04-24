"""Tests for ExperimentSummary + decomposition read/write + narrative format."""
from __future__ import annotations

from pathlib import Path

from apr_agent.api import (
    ExperimentSummary,
    get_experiment_summary,
    get_trajectory_for_summarization,
    load_trajectory,
    read_decomposed_steps,
    write_decomposed_steps,
)
from apr_agent.schema import BugSample
from apr_agent.trajectory.writer_jsonl import finalize_meta, init_bug_dir


def _seed(tmp_path: Path, bug_id: str, status: str) -> Path:
    bug = BugSample(bug_id=bug_id, project=bug_id.split("-")[0], bug_number=1,
                    buggy_checkout_dir="/tmp/x", trigger_tests=[], currently_failing=[],
                    trigger_test_output="", defects4j_version="2.0.1")
    bd = init_bug_dir(data_root=tmp_path / "data", exp_id="exp",
                      bug_sample=bug, tool_registry=[], meta_extras={})
    finalize_meta(bd, status=status)
    return tmp_path / "data"


def test_experiment_summary_counts(tmp_path: Path):
    _seed(tmp_path, "Math-1", "fixed")
    _seed(tmp_path, "Math-2", "fixed")
    _seed(tmp_path, "Lang-1", "failed")
    _seed(tmp_path, "Closure-1", "error")
    s = get_experiment_summary(tmp_path / "data", "exp")
    assert isinstance(s, ExperimentSummary)
    assert s.total == 4
    assert s.fixed == 2
    assert s.failed == 1
    assert s.error == 1
    assert s.fix_rate == 0.5
    assert set(s.bug_ids) == {"Math-1", "Math-2", "Lang-1", "Closure-1"}


def test_experiment_summary_missing_experiment_is_zero(tmp_path: Path):
    s = get_experiment_summary(tmp_path / "data", "nope")
    assert s.total == 0
    assert s.fix_rate == 0.0
    assert s.bug_ids == []


def test_decomposed_steps_roundtrip(tmp_path: Path):
    data_root = _seed(tmp_path, "Math-1", "fixed")
    assert read_decomposed_steps(data_root, "exp", "Math-1") is None
    steps = [
        {"step_id": 1, "kind": "locate", "summary": "Found off-by-one in add()"},
        {"step_id": 2, "kind": "edit",   "summary": "Swapped - for +"},
    ]
    write_decomposed_steps(data_root, "exp", "Math-1", steps)
    assert read_decomposed_steps(data_root, "exp", "Math-1") == steps


def test_decomposed_steps_on_missing_bug_raises(tmp_path: Path):
    import pytest
    with pytest.raises(FileNotFoundError):
        write_decomposed_steps(tmp_path / "data", "nope", "nope", [])


def test_summarization_narrative_format(tmp_path: Path):
    data_root = _seed(tmp_path, "Math-1", "fixed")
    tr = load_trajectory(data_root, "exp", "Math-1")
    text = get_trajectory_for_summarization(tr, format="narrative")
    assert isinstance(text, str)
    assert "Bug Math-1" in text
    assert "status=fixed" in text


def test_summarization_messages_includes_thinking(tmp_path: Path):
    from apr_agent.schema import Turn
    from apr_agent.trajectory.writer_jsonl import append_turn

    data_root = _seed(tmp_path, "Math-1", "fixed")
    bd = data_root / "trajectories" / "exp" / "Math-1"
    append_turn(bd, Turn(
        turn_idx=0, started_at=0, ended_at=1,
        request={"messages": [{"role": "system", "content": "sys"}]},
        response={"parsed": {"content": "fix it"}},
        thinking="secret CoT", usage={}, tool_calls=[],
    ))
    tr = load_trajectory(data_root, "exp", "Math-1")
    msgs = get_trajectory_for_summarization(tr, format="messages")
    assistant = [m for m in msgs if m["role"] == "assistant"][0]
    assert "<think>secret CoT</think>" in assistant["content"]
