from apr_agent.schema import BugSample, Event, ToolCall, Trajectory, Turn, VerifyResult


def test_bug_sample_roundtrip():
    s = BugSample(
        bug_id="Math-12",
        project="Math",
        bug_number=12,
        buggy_checkout_dir="/tmp/scratch/Math-12",
        trigger_tests=["org.apache.commons.math.TestFoo::bar"],
        currently_failing=["org.apache.commons.math.TestFoo::bar"],
        trigger_test_output="AssertionError: expected 1, got 2",
        defects4j_version="2.0.1",
    )
    dumped = s.model_dump()
    restored = BugSample.model_validate(dumped)
    assert restored == s
    assert restored.loc_hints is None
    assert restored.d4j_subset is None


def test_verify_result_defaults():
    v = VerifyResult(
        all_passing=True,
        previously_failing_now_passing=["t1"],
        newly_failing=[],
        patch_applied=True,
        test_exit_code=0,
        runtime_s=12.5,
        raw_output="",
    )
    assert v.all_passing is True


def test_schema_ignores_extra_fields():
    raw = {
        "bug_id": "Math-1",
        "project": "Math",
        "bug_number": 1,
        "buggy_checkout_dir": "/tmp/x",
        "trigger_tests": [],
        "currently_failing": [],
        "trigger_test_output": "",
        "defects4j_version": "2.0.1",
        "future_field_added_later": "ok",
    }
    parsed = BugSample.model_validate(raw)
    assert parsed.bug_id == "Math-1"


def test_tool_call_roundtrip():
    tc = ToolCall(
        call_id="c1",
        tool_name="read_file",
        tool_input={"path": "a.java", "start_line": 1, "end_line": 10},
        tool_output="... file contents ...",
        tool_meta={"exit_code": 0},
        started_at=1000.0,
        ended_at=1000.5,
        is_error=False,
    )
    assert ToolCall.model_validate(tc.model_dump()) == tc


def test_turn_has_tool_calls():
    t = Turn(
        turn_idx=0,
        started_at=1000.0,
        ended_at=1002.0,
        request={"messages": []},
        response={"content": "ok"},
        thinking=None,
        usage={"prompt_tokens": 10, "completion_tokens": 5},
        tool_calls=[],
    )
    assert t.turn_idx == 0
    assert t.tool_calls == []


def test_event_kind_validation():
    e = Event(
        event_id=0,
        turn_idx=0,
        at=1000.0,
        kind="turn_start",
        payload={},
    )
    assert e.kind == "turn_start"


def test_event_invalid_kind_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Event(event_id=0, turn_idx=0, at=0.0, kind="bogus", payload={})


def _sample_bug():
    return BugSample(
        bug_id="Math-12", project="Math", bug_number=12,
        buggy_checkout_dir="/tmp/x", trigger_tests=[], currently_failing=[],
        trigger_test_output="", defects4j_version="2.0.1",
    )


def test_trajectory_minimal():
    t = Trajectory(
        exp_id="exp1",
        bug_id="Math-12",
        status="running",
        bug_sample=_sample_bug(),
        turns=[],
        events=[],
        final_patch="",
        verify=None,
        tool_registry=[],
        meta={},
    )
    assert t.status == "running"
    assert Trajectory.model_validate(t.model_dump()) == t


def test_trajectory_status_invalid():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Trajectory(
            exp_id="e", bug_id="b", status="bogus",
            bug_sample=_sample_bug(), turns=[], events=[],
            final_patch="", verify=None, tool_registry=[], meta={},
        )
