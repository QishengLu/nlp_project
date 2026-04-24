from pathlib import Path

from apr_agent.api import get_turns_as_messages, load_trajectory
from apr_agent.schema import BugSample, ToolCall, Turn
from apr_agent.trajectory.writer_jsonl import append_turn, finalize_meta, init_bug_dir


def _make_traj(tmp_path: Path, thinking: str | None = None):
    data_root = tmp_path / "data"
    bug = BugSample(bug_id="Math-1", project="Math", bug_number=1,
                    buggy_checkout_dir="/x", trigger_tests=[], currently_failing=[],
                    trigger_test_output="", defects4j_version="2.0.1")
    bd = init_bug_dir(data_root=data_root, exp_id="e", bug_sample=bug,
                      tool_registry=[], meta_extras={})
    t0 = Turn(
        turn_idx=0, started_at=0, ended_at=1,
        request={"messages": [
            {"role": "system", "content": "You are an APR agent."},
            {"role": "user", "content": "Fix Math-1."},
        ]},
        response={"content": "I'll read the file first."},
        thinking=thinking,
        usage={}, tool_calls=[
            ToolCall(call_id="c1", tool_name="read_file",
                     tool_input={"path": "Foo.java"},
                     tool_output="file contents",
                     tool_meta={}, started_at=0.1, ended_at=0.2, is_error=False),
        ],
    )
    t1 = Turn(
        turn_idx=1, started_at=1, ended_at=2,
        request={"messages": []},
        response={"content": "Done."},
        thinking=None, usage={}, tool_calls=[],
    )
    append_turn(bd, t0)
    append_turn(bd, t1)
    finalize_meta(bd, status="fixed")
    return load_trajectory(data_root, "e", "Math-1")


def test_get_turns_as_messages_basic(tmp_path: Path):
    tr = _make_traj(tmp_path)
    msgs = get_turns_as_messages(tr)

    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool", "assistant"]
    assert msgs[0]["content"] == "You are an APR agent."
    assert msgs[2]["content"] == "I'll read the file first."
    assert msgs[2]["tool_calls"][0]["function"]["name"] == "read_file"
    assert msgs[3]["tool_call_id"] == "c1"
    assert msgs[3]["content"] == "file contents"
    assert msgs[4]["content"] == "Done."


def test_get_turns_as_messages_thinking_excluded_by_default(tmp_path: Path):
    tr = _make_traj(tmp_path, thinking="internal thought")
    msgs = get_turns_as_messages(tr, include_thinking=False)
    assert "<think>" not in msgs[2]["content"]


def test_get_turns_as_messages_thinking_included(tmp_path: Path):
    tr = _make_traj(tmp_path, thinking="internal thought")
    msgs = get_turns_as_messages(tr, include_thinking=True)
    assert "<think>internal thought</think>" in msgs[2]["content"]


def test_get_turns_as_messages_no_system(tmp_path: Path):
    tr = _make_traj(tmp_path)
    msgs = get_turns_as_messages(tr, include_system=False)
    assert msgs[0]["role"] == "user"
