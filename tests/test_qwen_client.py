"""Unit tests for QwenClient response parsing + sensitive-data scrubbing.

No real API calls here — those live behind @pytest.mark.needs_api_key.
"""
from __future__ import annotations

import pytest

from apr_agent.llm.qwen import (
    QwenClient,
    QwenConfig,
    mask_sensitive_request,
    parse_openai_response,
)


def test_parse_inline_think_tag():
    raw = {
        "choices": [{
            "finish_reason": "stop",
            "message": {
                "role": "assistant",
                "content": "<think>let me step back</think>Here is the fix.",
                "tool_calls": None,
            },
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    r = parse_openai_response(raw)
    assert r.thinking == "let me step back"
    assert r.content == "Here is the fix."
    assert r.stop_reason == "stop"
    assert r.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def test_parse_reasoning_content_takes_priority():
    raw = {
        "choices": [{
            "finish_reason": "stop",
            "message": {
                "role": "assistant",
                "content": "visible reply",
                "reasoning_content": "hidden CoT",
            },
        }],
        "usage": {},
    }
    r = parse_openai_response(raw)
    assert r.thinking == "hidden CoT"
    assert r.content == "visible reply"


def test_parse_tool_calls():
    raw = {
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "read_file",
                                  "arguments": '{"path":"Foo.java"}'}},
                ],
            },
        }],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    r = parse_openai_response(raw)
    assert r.stop_reason == "tool_calls"
    assert r.tool_calls[0]["function"]["name"] == "read_file"
    assert r.tool_calls[0]["function"]["arguments"] == '{"path":"Foo.java"}'


def test_parse_missing_usage_zeros():
    raw = {
        "choices": [{"finish_reason": "stop",
                     "message": {"role": "assistant", "content": "ok"}}],
    }
    r = parse_openai_response(raw)
    assert r.usage == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def test_parse_empty_choices_is_safe():
    r = parse_openai_response({"choices": []})
    assert r.content == ""
    assert r.tool_calls == []
    assert r.usage["prompt_tokens"] == 0


def test_mask_sensitive_scrubs_authorization_anywhere():
    body = {
        "headers": {"Authorization": "Bearer sk-secret", "Content-Type": "application/json"},
        "nested": {"api_key": "should-be-kept"},  # different key — only exact matches scrubbed
        "list": [{"authorization": "Bearer sk-xyz"}, {"foo": "bar"}],
    }
    out = mask_sensitive_request(body)
    assert out["headers"]["Authorization"] == "***REDACTED***"
    assert out["headers"]["Content-Type"] == "application/json"
    assert out["list"][0]["authorization"] == "***REDACTED***"
    assert out["list"][1]["foo"] == "bar"
    # Original object must be untouched.
    assert body["headers"]["Authorization"] == "Bearer sk-secret"


def test_mask_sensitive_hits_api_key_variants():
    out = mask_sensitive_request({"api-key": "x", "API-KEY": "y", "other": "z"})
    assert out["api-key"] == "***REDACTED***"
    assert out["API-KEY"] == "***REDACTED***"
    assert out["other"] == "z"


def test_qwen_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="No API key"):
        QwenClient(QwenConfig())


# --- live smoke — runs only when key present; prints response shape ---

@pytest.mark.needs_api_key
@pytest.mark.slow
def test_qwen_live_smoke_single_turn():
    """Minimal end-to-end: produces ChatResponse with non-empty content and usage."""
    client = QwenClient(QwenConfig(enable_thinking=False))
    r = client.chat(
        messages=[{"role": "user", "content": "Say only: OK"}],
        tools=[],
        max_tokens=32,
    )
    assert r.content, "expected non-empty content"
    assert r.usage["prompt_tokens"] >= 0
    assert r.usage["completion_tokens"] >= 0
