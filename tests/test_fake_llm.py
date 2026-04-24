from apr_agent.llm.fake import FakeLLMClient, ScriptedResponse


def test_fake_llm_plays_back_scripted_responses():
    client = FakeLLMClient(
        script=[
            ScriptedResponse(content="thinking about it", tool_calls=[
                {"id": "c1", "name": "finish", "arguments": {"rationale": "ok"}}
            ]),
        ]
    )
    r = client.chat(messages=[{"role": "user", "content": "fix Math-1"}], tools=[])
    assert r.content == "thinking about it"
    assert r.tool_calls[0]["function"]["name"] == "finish"
    assert r.usage["prompt_tokens"] == 0


def test_fake_llm_exhaustion_raises():
    client = FakeLLMClient(script=[])
    import pytest
    with pytest.raises(RuntimeError):
        client.chat(messages=[], tools=[])


def test_fake_llm_usage_has_required_keys():
    """Contract: every Turn.usage MUST have prompt_tokens and completion_tokens."""
    client = FakeLLMClient(script=[ScriptedResponse(content="x")])
    r = client.chat(messages=[], tools=[])
    assert "prompt_tokens" in r.usage
    assert "completion_tokens" in r.usage
    assert isinstance(r.usage["prompt_tokens"], int)
    assert isinstance(r.usage["completion_tokens"], int)
