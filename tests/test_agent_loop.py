from pathlib import Path

from apr_agent.agent.loop import AgentConfig, AgentLoop
from apr_agent.llm.fake import FakeLLMClient, ScriptedResponse
from apr_agent.schema import BugSample
from apr_agent.tools.finish import FinishTool
from apr_agent.tools.registry import ToolRegistry


def _bug():
    return BugSample(bug_id="Math-1", project="Math", bug_number=1,
                     buggy_checkout_dir="/tmp/x", trigger_tests=[], currently_failing=[],
                     trigger_test_output="", defects4j_version="2.0.1")


def test_loop_terminates_on_finish(tmp_path: Path):
    fake = FakeLLMClient(script=[
        ScriptedResponse(content="I'll call finish.", tool_calls=[
            {"id": "c1", "name": "finish", "arguments": {"rationale": "done"}},
        ]),
    ])
    reg = ToolRegistry()
    reg.register(FinishTool())

    loop = AgentLoop(
        llm=fake,
        tools=reg,
        config=AgentConfig(max_turns=5, system_prompt="You are an APR agent.",
                           user_prompt_template="Fix {bug_id}."),
    )
    stop_reason, turns = loop.run(_bug())

    assert stop_reason == "finish"
    assert len(turns) == 1
    assert turns[0].tool_calls[0].tool_name == "finish"
    assert turns[0].tool_calls[0].tool_input == {"rationale": "done"}


def test_loop_respects_max_turns(tmp_path: Path):
    fake = FakeLLMClient(script=[
        ScriptedResponse(content="a"),
        ScriptedResponse(content="b"),
        ScriptedResponse(content="c"),
    ])
    reg = ToolRegistry()
    loop = AgentLoop(
        llm=fake,
        tools=reg,
        config=AgentConfig(max_turns=2, system_prompt="sys", user_prompt_template="fix {bug_id}"),
    )
    stop_reason, turns = loop.run(_bug())
    assert stop_reason == "max_turns"
    assert len(turns) == 2


def test_loop_survives_malformed_tool_arguments(tmp_path: Path):
    """Small models frequently emit invalid JSON in tool_calls. The loop must
    record the failure as is_error=True and keep going, so the LLM sees its own
    mistake in the next turn and can self-correct."""
    from apr_agent.llm.client import ChatResponse

    class BadJSONClient:
        def __init__(self):
            self._calls = 0

        def chat(self, *, messages, tools, temperature=0.2, max_tokens=4096):
            self._calls += 1
            if self._calls == 1:
                return ChatResponse(
                    content="let me fix it",
                    tool_calls=[{"id": "c1", "type": "function",
                                 "function": {"name": "finish",
                                              "arguments": "{not valid json"}}],
                    stop_reason="tool_calls", thinking=None,
                    usage={"prompt_tokens": 0, "completion_tokens": 0},
                    raw={},
                )
            return ChatResponse(
                content="retry", tool_calls=[{"id": "c2", "type": "function",
                                              "function": {"name": "finish",
                                                           "arguments": '{"rationale":"ok"}'}}],
                stop_reason="tool_calls", thinking=None,
                usage={"prompt_tokens": 0, "completion_tokens": 0},
                raw={},
            )

    reg = ToolRegistry()
    reg.register(FinishTool())
    loop = AgentLoop(
        llm=BadJSONClient(), tools=reg,
        config=AgentConfig(max_turns=5, system_prompt="s", user_prompt_template="f {bug_id}"),
    )
    stop_reason, turns = loop.run(_bug())
    assert stop_reason == "finish"
    assert len(turns) == 2
    bad = turns[0].tool_calls[0]
    assert bad.is_error is True
    assert bad.tool_meta["error"] == "malformed_tool_arguments"
    assert "parse_error" in bad.tool_meta
    assert turns[1].tool_calls[0].is_error is False
