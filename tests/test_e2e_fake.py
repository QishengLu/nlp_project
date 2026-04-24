"""End-to-end: FakeLLM + AgentLoop + TrajectoryRecorder → on-disk trajectory → read back."""
from pathlib import Path

from apr_agent.agent.loop import AgentConfig, AgentLoop
from apr_agent.api import get_turns_as_messages, iter_trajectories, load_trajectory
from apr_agent.llm.fake import FakeLLMClient, ScriptedResponse
from apr_agent.schema import BugSample
from apr_agent.tools.finish import FinishTool
from apr_agent.tools.registry import ToolRegistry
from apr_agent.trajectory.recorder import TrajectoryRecorder


def test_fake_e2e_produces_loadable_trajectory(tmp_path: Path):
    bug = BugSample(
        bug_id="Math-12", project="Math", bug_number=12,
        buggy_checkout_dir="/tmp/x",
        trigger_tests=["org.apache.commons.math.TestFoo::bar"],
        currently_failing=["org.apache.commons.math.TestFoo::bar"],
        trigger_test_output="AssertionError",
        defects4j_version="2.0.1",
    )

    fake = FakeLLMClient(script=[
        ScriptedResponse(
            content="I'll finish now.", thinking="let me think",
            tool_calls=[{"id": "c1", "name": "finish",
                         "arguments": {"rationale": "fake fix"}}],
        ),
    ])
    reg = ToolRegistry()
    reg.register(FinishTool())

    rec = TrajectoryRecorder.start(
        data_root=tmp_path / "data", exp_id="fake-exp-1",
        bug_sample=bug,
        tool_registry=reg.openai_schemas(),
        meta_extras={"model_name": "fake-llm", "apr_agent_version": "0.1.0"},
    )

    loop = AgentLoop(
        llm=fake, tools=reg,
        config=AgentConfig(max_turns=5,
                           system_prompt="You are an APR agent.",
                           user_prompt_template="Fix {bug_id}. Trigger: {trigger_tests}"),
    )
    stop_reason, turns = loop.run(bug)
    for turn in turns:
        rec.record_turn(turn)

    rec.finalize(status="fixed" if stop_reason == "finish" else "failed",
                 extra={"stop_reason": stop_reason, "duration_s": 0.0})

    tr = load_trajectory(tmp_path / "data", "fake-exp-1", "Math-12")
    assert tr.status == "fixed"
    assert len(tr.turns) == 1
    assert tr.turns[0].tool_calls[0].tool_name == "finish"
    assert tr.turns[0].thinking == "let me think"
    assert tr.meta["model_name"] == "fake-llm"
    # 4 derived events: llm_response + tool_call_start + tool_call_end + turn_end
    # (no manual turn_start in this flow)
    assert len(tr.events) == 4

    fixed = list(iter_trajectories(tmp_path / "data", "fake-exp-1", only_fixed=True))
    assert len(fixed) == 1

    msgs = get_turns_as_messages(tr, include_thinking=True)
    roles = [m["role"] for m in msgs]
    assert roles == ["system", "user", "assistant", "tool"]
    assert "<think>let me think</think>" in msgs[2]["content"]
    assert msgs[3]["content"] == ""
