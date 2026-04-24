"""Qwen client via openai SDK against DashScope's OpenAI-compatible endpoint.

M3 reality check: the thinking-content carrier for `qwen3-coder-30b-a3b-instruct`
on DashScope is NOT verified yet. Documented hypotheses:
- inline <think>...</think> in message.content (self-hosted Qwen3-Thinking)
- message.reasoning_content field (DashScope thinking-enabled models)
- enable_thinking=true may be silently ignored / rejected by this -Instruct variant

Run `python scripts/qwen_smoke.py` with a real API key first, then tighten the
parser here. The current implementation reads both candidates so we don't lose
data whichever shape DashScope actually ships.
"""
from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass

from apr_agent.llm.client import ChatResponse

_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_SENSITIVE_HEADER_KEYS = {"authorization", "x-api-key", "api-key"}

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)


@dataclass
class QwenConfig:
    model: str = "qwen3-coder-30b-a3b-instruct"
    base_url: str = _DEFAULT_BASE_URL
    api_key_env: str = "DASHSCOPE_API_KEY"
    api_key_env_fallback: str = "QWEN_API_KEY"
    enable_thinking: bool = True
    extra_body: dict | None = None


class QwenClient:
    """openai.OpenAI wrapper. Satisfies the `LLMClient` Protocol."""

    def __init__(self, config: QwenConfig | None = None):
        from openai import OpenAI  # lazy import so tests that don't need Qwen don't pay

        self.config = config or QwenConfig()
        key = os.getenv(self.config.api_key_env) or os.getenv(self.config.api_key_env_fallback)
        if not key:
            raise RuntimeError(
                f"No API key found in ${self.config.api_key_env} / "
                f"${self.config.api_key_env_fallback}"
            )
        self._client = OpenAI(base_url=self.config.base_url, api_key=key)

    def chat(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> ChatResponse:
        call_kwargs: dict = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            call_kwargs["tools"] = tools
            call_kwargs["tool_choice"] = "auto"
        extra = dict(self.config.extra_body or {})
        if self.config.enable_thinking:
            # DashScope accepts this via extra_body for models that support it;
            # models that don't may ignore or 400. Smoke the endpoint first.
            extra.setdefault("enable_thinking", True)
        if extra:
            call_kwargs["extra_body"] = extra

        resp = self._client.chat.completions.create(**call_kwargs)
        raw = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        return parse_openai_response(raw)


def parse_openai_response(raw: dict) -> ChatResponse:
    """Turn a DashScope/OpenAI-shape dump into a ChatResponse. Exposed for testing."""
    choices = raw.get("choices") or []
    if not choices:
        return ChatResponse(content="", tool_calls=[], stop_reason="stop",
                            thinking=None, usage=_zero_usage(), raw=raw)

    msg = choices[0].get("message") or {}
    content = msg.get("content") or ""
    stop_reason = choices[0].get("finish_reason") or "stop"

    # Thinking: prefer reasoning_content (DashScope thinking models), then inline <think>.
    thinking = msg.get("reasoning_content")
    if not thinking:
        m = _THINK_RE.search(content)
        if m:
            thinking = m.group(1).strip()
            content = _THINK_RE.sub("", content).strip()

    tool_calls: list[dict] = []
    for tc in msg.get("tool_calls") or []:
        # OpenAI SDK returns tool_calls with id/type/function{name,arguments}
        fn = tc.get("function") or {}
        tool_calls.append({
            "id": tc.get("id"),
            "type": tc.get("type", "function"),
            "function": {
                "name": fn.get("name"),
                "arguments": fn.get("arguments", "{}"),
            },
        })

    usage = raw.get("usage") or {}
    # Normalize to our contract: prompt_tokens + completion_tokens (0 if missing).
    normalized_usage = {
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }

    return ChatResponse(
        content=content,
        tool_calls=tool_calls,
        stop_reason=stop_reason,
        thinking=thinking,
        usage=normalized_usage,
        raw=raw,
    )


def _zero_usage() -> dict:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def mask_sensitive_request(request_body: dict) -> dict:
    """Return a deep-copy of request_body with auth headers masked.

    The AgentLoop stores request bodies in Turn.request so downstream can replay.
    We never want API keys to survive into the trajectory — even if the openai
    SDK adds Authorization to kwargs in some code path, this sanitizer catches it.
    """
    body = copy.deepcopy(request_body)
    _scrub_headers(body)
    return body


def _scrub_headers(obj) -> None:
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if isinstance(k, str) and k.lower() in _SENSITIVE_HEADER_KEYS:
                obj[k] = "***REDACTED***"
            else:
                _scrub_headers(v)
    elif isinstance(obj, list):
        for item in obj:
            _scrub_headers(item)
