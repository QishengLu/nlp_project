"""LLM client interface — real and fake implementations both satisfy this."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ChatResponse:
    content: str
    tool_calls: list[dict]   # OpenAI-shaped: [{id, type, function: {name, arguments}}]
    stop_reason: str
    thinking: str | None
    usage: dict              # {prompt_tokens, completion_tokens, ...}
    raw: dict                # original provider response (serialised)


class LLMClient(Protocol):
    def chat(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> ChatResponse: ...
