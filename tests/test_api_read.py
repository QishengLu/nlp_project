from pathlib import Path

from apr_agent.api import load_trajectory
from apr_agent.schema import BugSample, Event, Turn, VerifyResult
from apr_agent.trajectory.writer_jsonl import (
    append_event, append_turn, finalize_meta,
    init_bug_dir, write_final_patch, write_verify_result,
)


def _seed_bug(tmp_path: Path, exp_id="exp1", bug_id="Math-12"):
    data_root = tmp_path / "data"
    bug = BugSample(bug_id=bug_id, project="Math", bug_number=12,
                    buggy_checkout_dir="/tmp/x", trigger_tests=["t1"],
                    currently_failing=["t1"], trigger_test_output="",
                    defects4j_version="2.0.1")
    bd = init_bug_dir(data_root=data_root, exp_id=exp_id, bug_sample=bug,
                      tool_registry=[{"name": "finish"}],
                      meta_extras={"model_name": "fake"})
    t = Turn(turn_idx=0, started_at=0, ended_at=1, request={}, response={},
             thinking="thinking text", usage={}, tool_calls=[])
    append_turn(bd, t)
    append_event(bd, Event(event_id=0, turn_idx=0, at=0, kind="turn_start", payload={}))
    append_event(bd, Event(event_id=1, turn_idx=0, at=1, kind="turn_end", payload={}))
    write_final_patch(bd, "--- a\n+++ b\n")
    write_verify_result(bd, VerifyResult(
        all_passing=True, previously_failing_now_passing=["t1"], newly_failing=[],
        patch_applied=True, test_exit_code=0, runtime_s=1.0, raw_output="",
    ))
    finalize_meta(bd, status="fixed", extra={"duration_s": 1.0})
    return data_root


def test_load_trajectory_roundtrip(tmp_path: Path):
    data_root = _seed_bug(tmp_path)
    tr = load_trajectory(data_root, "exp1", "Math-12")
    assert tr.bug_id == "Math-12"
    assert tr.status == "fixed"
    assert len(tr.turns) == 1
    assert tr.turns[0].thinking == "thinking text"
    assert len(tr.events) == 2
    assert tr.final_patch == "--- a\n+++ b\n"
    assert tr.verify is not None
    assert tr.verify.all_passing is True
    assert tr.tool_registry == [{"name": "finish"}]
    assert tr.meta["model_name"] == "fake"
    assert tr.meta["duration_s"] == 1.0
    assert tr.meta["schema_version"] == "1.0"


def test_load_trajectory_rejects_incompatible_schema_version(tmp_path: Path):
    import json as _json

    import pytest

    from apr_agent.api import SchemaVersionError

    data_root = _seed_bug(tmp_path)
    meta_path = data_root / "trajectories" / "exp1" / "Math-12" / "meta.json"
    meta = _json.loads(meta_path.read_text())
    meta["schema_version"] = "2.0"
    meta_path.write_text(_json.dumps(meta))

    with pytest.raises(SchemaVersionError):
        load_trajectory(data_root, "exp1", "Math-12")


def test_package_root_exports():
    import apr_agent
    assert hasattr(apr_agent, "load_trajectory")
    assert hasattr(apr_agent, "Trajectory")


from apr_agent.api import iter_trajectories, list_bugs, list_experiments


def _seed_two_bugs(tmp_path: Path, exp_id="exp1"):
    _seed_bug(tmp_path, exp_id=exp_id, bug_id="Math-12")
    # Second bug: mark as failed
    bug = BugSample(bug_id="Lang-1", project="Lang", bug_number=1,
                    buggy_checkout_dir="/tmp/x", trigger_tests=[],
                    currently_failing=[], trigger_test_output="",
                    defects4j_version="2.0.1")
    bd = init_bug_dir(data_root=tmp_path / "data", exp_id=exp_id, bug_sample=bug,
                      tool_registry=[], meta_extras={})
    finalize_meta(bd, status="failed")
    return tmp_path / "data"


def test_list_experiments_and_bugs(tmp_path: Path):
    data_root = _seed_two_bugs(tmp_path)
    assert list_experiments(data_root) == ["exp1"]
    bugs = list_bugs(data_root, "exp1")
    assert sorted(bugs) == ["Lang-1", "Math-12"]


def test_list_bugs_status_filter(tmp_path: Path):
    data_root = _seed_two_bugs(tmp_path)
    fixed = list_bugs(data_root, "exp1", status_filter={"fixed"})
    assert fixed == ["Math-12"]


def test_iter_trajectories_only_fixed(tmp_path: Path):
    data_root = _seed_two_bugs(tmp_path)
    fixed = list(iter_trajectories(data_root, "exp1", only_fixed=True))
    assert len(fixed) == 1
    assert fixed[0].bug_id == "Math-12"
