"""Scripted fake LLM client for tests."""
from __future__ import annotations

import json as _json
from dataclasses import dataclass, field

from apr_agent.llm.client import ChatResponse


@dataclass
class ScriptedResponse:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)  # [{id, name, arguments}]
    stop_reason: str = "stop"
    thinking: str | None = None


class FakeLLMClient:
    def __init__(self, script: list[ScriptedResponse]):
        self._script = list(script)
        self._idx = 0

    def chat(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> ChatResponse:
        if self._idx >= len(self._script):
            raise RuntimeError("FakeLLMClient script exhausted")
        step = self._script[self._idx]
        self._idx += 1

        oa_tool_calls = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": _json.dumps(tc["arguments"], ensure_ascii=False),
                },
            }
            for tc in step.tool_calls
        ]

        return ChatResponse(
            content=step.content,
            tool_calls=oa_tool_calls,
            stop_reason=step.stop_reason,
            thinking=step.thinking,
            usage={"prompt_tokens": 0, "completion_tokens": 0},
            raw={"content": step.content, "tool_calls": oa_tool_calls,
                 "stop_reason": step.stop_reason, "thinking": step.thinking},
        )
