from pathlib import Path

from apr_agent.schema import BugSample, ToolCall, Turn
from apr_agent.trajectory.recorder import TrajectoryRecorder


def _bug():
    return BugSample(bug_id="Math-12", project="Math", bug_number=12,
                     buggy_checkout_dir="/tmp/x", trigger_tests=[], currently_failing=[],
                     trigger_test_output="", defects4j_version="2.0.1")


def test_recorder_full_flow(tmp_path: Path):
    r = TrajectoryRecorder.start(
        data_root=tmp_path / "data",
        exp_id="e",
        bug_sample=_bug(),
        tool_registry=[{"name": "finish"}],
        meta_extras={"model_name": "fake"},
    )
    r.emit("turn_start", turn_idx=0, payload={"msg": "hi"})
    r.record_turn(Turn(
        turn_idx=0, started_at=0, ended_at=1,
        request={}, response={"content": "ok"},
        thinking=None, usage={},
        tool_calls=[ToolCall(call_id="c1", tool_name="finish",
                             tool_input={"rationale": "done"}, tool_output="",
                             tool_meta={}, started_at=0, ended_at=0.1, is_error=False)],
    ))
    r.finalize(status="fixed", extra={"duration_s": 1.0})

    from apr_agent.api import load_trajectory
    tr = load_trajectory(tmp_path / "data", "e", "Math-12")
    assert tr.status == "fixed"
    assert len(tr.turns) == 1
    # manual turn_start + auto (llm_response + tool_call_start + tool_call_end + turn_end) = 5
    assert len(tr.events) == 5
    assert tr.events[0].kind == "turn_start"
    assert tr.events[1].kind == "llm_response"
    assert tr.events[-1].kind == "turn_end"


def test_recorder_event_ids_are_monotonic(tmp_path: Path):
    r = TrajectoryRecorder.start(
        data_root=tmp_path / "data",
        exp_id="e", bug_sample=_bug(),
        tool_registry=[], meta_extras={},
    )
    r.emit("turn_start", turn_idx=0, payload={})
    r.emit("turn_end", turn_idx=0, payload={})
    r.finalize(status="aborted")

    from apr_agent.api import load_trajectory
    tr = load_trajectory(tmp_path / "data", "e", "Math-12")
    ids = [e.event_id for e in tr.events]
    assert ids == sorted(ids)
    assert ids == list(range(len(ids)))
