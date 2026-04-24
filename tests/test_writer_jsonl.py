import json
from pathlib import Path

from apr_agent.schema import BugSample, VerifyResult
from apr_agent.trajectory.writer_jsonl import (
    bug_dir_for,
    finalize_meta,
    init_bug_dir,
    write_final_patch,
    write_verify_result,
)


def _bug():
    return BugSample(
        bug_id="Math-12", project="Math", bug_number=12,
        buggy_checkout_dir="/tmp/x", trigger_tests=["t1"], currently_failing=["t1"],
        trigger_test_output="out", defects4j_version="2.0.1",
    )


def test_init_bug_dir_creates_files(tmp_path: Path):
    data_root = tmp_path / "data"
    bug_dir = init_bug_dir(
        data_root=data_root,
        exp_id="exp1",
        bug_sample=_bug(),
        tool_registry=[{"name": "read_file"}],
        meta_extras={"model_name": "qwen"},
    )
    assert bug_dir == bug_dir_for(data_root, "exp1", "Math-12")
    assert bug_dir.is_dir()
    assert (bug_dir / "bug_sample.json").exists()
    assert (bug_dir / "tool_registry.json").exists()
    meta = json.loads((bug_dir / "meta.json").read_text())
    assert meta["status"] == "running"
    assert meta["bug_id"] == "Math-12"
    assert meta["model_name"] == "qwen"
    assert meta["schema_version"] == "1.0"
    assert (bug_dir / "turns.jsonl").exists()
    assert (bug_dir / "events.jsonl").exists()


def test_init_bug_dir_moves_existing_to_trash(tmp_path: Path):
    data_root = tmp_path / "data"
    init_bug_dir(data_root=data_root, exp_id="exp1", bug_sample=_bug(),
                 tool_registry=[], meta_extras={})
    init_bug_dir(data_root=data_root, exp_id="exp1", bug_sample=_bug(),
                 tool_registry=[], meta_extras={})
    exp_dir = data_root / "trajectories" / "exp1"
    trash_dirs = [p for p in exp_dir.iterdir() if p.name.startswith("Math-12.trash-")]
    assert len(trash_dirs) == 1


def test_write_final_patch_and_verify(tmp_path: Path):
    data_root = tmp_path / "data"
    bug_dir = init_bug_dir(data_root=data_root, exp_id="exp1", bug_sample=_bug(),
                           tool_registry=[], meta_extras={})
    write_final_patch(bug_dir, "--- a\n+++ b\n")
    v = VerifyResult(
        all_passing=True, previously_failing_now_passing=["t1"], newly_failing=[],
        patch_applied=True, test_exit_code=0, runtime_s=1.0, raw_output="",
    )
    write_verify_result(bug_dir, v)

    assert (bug_dir / "final_patch.diff").read_text() == "--- a\n+++ b\n"
    loaded = json.loads((bug_dir / "verify_result.json").read_text())
    assert loaded["all_passing"] is True


def test_finalize_meta_atomic(tmp_path: Path):
    data_root = tmp_path / "data"
    bug_dir = init_bug_dir(data_root=data_root, exp_id="exp1", bug_sample=_bug(),
                           tool_registry=[], meta_extras={})
    finalize_meta(bug_dir, status="fixed", extra={"duration_s": 42.0})
    meta = json.loads((bug_dir / "meta.json").read_text())
    assert meta["status"] == "fixed"
    assert meta["duration_s"] == 42.0
