"""Contract test — what the two downstream teammates will actually call.

If you change anything here, you're changing the public contract.
Bump version and coordinate with downstream.
"""
from pathlib import Path

import apr_agent
from apr_agent import (
    BugSample,
    Event,
    Trajectory,
    Turn,
    VerifyResult,
    get_turns_as_messages,
    iter_trajectories,
    list_bugs,
    list_experiments,
    load_trajectory,
)


def _seed_minimal(tmp_path: Path):
    """Use the public loop + recorder stack to produce a real trajectory."""
    from apr_agent.agent.loop import AgentConfig, AgentLoop
    from apr_agent.llm.fake import FakeLLMClient, ScriptedResponse
    from apr_agent.tools.finish import FinishTool
    from apr_agent.tools.registry import ToolRegistry
    from apr_agent.trajectory.recorder import TrajectoryRecorder

    bug = BugSample(bug_id="B-1", project="B", bug_number=1,
                    buggy_checkout_dir="/tmp/x", trigger_tests=[], currently_failing=[],
                    trigger_test_output="", defects4j_version="2.0.1")
    fake = FakeLLMClient(script=[ScriptedResponse(content="done",
        tool_calls=[{"id": "c1", "name": "finish", "arguments": {"rationale": "r"}}])])
    reg = ToolRegistry()
    reg.register(FinishTool())
    rec = TrajectoryRecorder.start(data_root=tmp_path / "data", exp_id="exp",
                                   bug_sample=bug, tool_registry=reg.openai_schemas(),
                                   meta_extras={"model_name": "fake"})
    loop = AgentLoop(llm=fake, tools=reg,
                     config=AgentConfig(max_turns=3, system_prompt="s",
                                        user_prompt_template="fix {bug_id}"))
    _, turns = loop.run(bug)
    for t in turns:
        rec.record_turn(t)
    rec.finalize(status="fixed", extra={"duration_s": 0.0})


def test_downstream_read_flow(tmp_path: Path):
    _seed_minimal(tmp_path)
    data_root = tmp_path / "data"

    # Simulate a downstream pipeline consuming fixed trajectories as SFT input.
    sft_records: list[dict] = []
    for tr in iter_trajectories(data_root, "exp", only_fixed=True):
        assert isinstance(tr, Trajectory)
        msgs = get_turns_as_messages(tr, include_thinking=False)
        sft_records.append({
            "bug_id": tr.bug_id,
            "messages": msgs,
            "final_patch": tr.final_patch,
        })
    assert len(sft_records) == 1
    assert sft_records[0]["bug_id"] == "B-1"


def test_listing_surface(tmp_path: Path):
    _seed_minimal(tmp_path)
    assert list_experiments(tmp_path / "data") == ["exp"]
    assert list_bugs(tmp_path / "data", "exp") == ["B-1"]


def test_schema_types_are_exported():
    # Downstream writes type hints against these names:
    assert apr_agent.Trajectory is Trajectory
    assert apr_agent.Turn is Turn
    assert apr_agent.Event is Event
    assert apr_agent.BugSample is BugSample
    assert apr_agent.VerifyResult is VerifyResult


def test_load_trajectory_single(tmp_path: Path):
    _seed_minimal(tmp_path)
    tr = load_trajectory(tmp_path / "data", "exp", "B-1")
    assert tr.status == "fixed"
    assert tr.bug_id == "B-1"
