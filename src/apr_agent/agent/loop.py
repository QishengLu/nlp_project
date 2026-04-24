"""Tool-use while loop. LLM-agnostic; takes an LLMClient + ToolRegistry."""
from __future__ import annotations

import json as _json
import time
from dataclasses import dataclass

from apr_agent.llm.client import LLMClient
from apr_agent.llm.qwen import mask_sensitive_request
from apr_agent.schema import BugSample, ToolCall, Turn
from apr_agent.tools.registry import ToolRegistry


@dataclass
class AgentConfig:
    max_turns: int
    system_prompt: str
    user_prompt_template: str  # e.g. "Fix bug {bug_id}. Trigger tests: {trigger_tests}"
    temperature: float = 0.2
    max_tokens: int = 4096


class AgentLoop:
    def __init__(self, *, llm: LLMClient, tools: ToolRegistry, config: AgentConfig):
        self.llm = llm
        self.tools = tools
        self.config = config

    def run(self, bug: BugSample) -> tuple[str, list[Turn]]:
        """Drive the tool-use loop. Returns (stop_reason, turns)."""
        messages: list[dict] = [
            {"role": "system", "content": self.config.system_prompt},
            {"role": "user", "content": self.config.user_prompt_template.format(
                bug_id=bug.bug_id,
                trigger_tests=", ".join(bug.trigger_tests),
                trigger_test_output=bug.trigger_test_output,
            )},
        ]
        tool_schemas = self.tools.openai_schemas()
        turns: list[Turn] = []

        for turn_idx in range(self.config.max_turns):
            started = time.time()
            request_body = {
                "messages": list(messages),
                "tools": tool_schemas,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            }
            resp = self.llm.chat(
                messages=messages, tools=tool_schemas,
                temperature=self.config.temperature, max_tokens=self.config.max_tokens,
            )

            tool_calls_record: list[ToolCall] = []
            terminated = False
            for tc in resp.tool_calls:
                fn = tc["function"]
                tool_name = fn["name"]
                t_start = time.time()
                # Parse arguments. LLMs (especially small ones) sometimes emit
                # malformed JSON — we MUST keep the loop alive so it can self-correct.
                try:
                    tool_input = _json.loads(fn["arguments"])
                    parse_error = None
                except _json.JSONDecodeError as e:
                    tool_input = {}
                    parse_error = f"{type(e).__name__}: {e}"
                if parse_error is not None:
                    out, meta, is_err = (
                        "",
                        {"error": "malformed_tool_arguments",
                         "parse_error": parse_error,
                         "raw_arguments": fn["arguments"]},
                        True,
                    )
                elif tool_name in self.tools:
                    tool = self.tools.get(tool_name)
                    result = tool.invoke(tool_input)
                    out, meta, is_err = result.output, result.meta, result.is_error
                    if tool.terminates_loop:
                        terminated = True
                else:
                    out, meta, is_err = "", {"error": f"unknown tool {tool_name}"}, True
                t_end = time.time()
                tool_calls_record.append(ToolCall(
                    call_id=tc["id"], tool_name=tool_name,
                    tool_input=tool_input, tool_output=out, tool_meta=meta,
                    started_at=t_start, ended_at=t_end, is_error=is_err,
                ))

            ended = time.time()
            turn = Turn(
                turn_idx=turn_idx,
                started_at=started, ended_at=ended,
                request=mask_sensitive_request(request_body),
                response={
                    "parsed": {
                        "content": resp.content,
                        "stop_reason": resp.stop_reason,
                        "tool_calls": resp.tool_calls,
                    },
                    "raw": resp.raw,
                },
                thinking=resp.thinking,
                usage=resp.usage,
                tool_calls=tool_calls_record,
            )
            turns.append(turn)

            # Build messages for next turn (so the LLM sees its own prior outputs).
            assistant_msg: dict = {"role": "assistant", "content": resp.content}
            if resp.tool_calls:
                assistant_msg["tool_calls"] = resp.tool_calls
            messages.append(assistant_msg)
            for tcr in tool_calls_record:
                messages.append({
                    "role": "tool", "tool_call_id": tcr.call_id, "content": tcr.tool_output,
                })

            if terminated:
                return "finish", turns

        return "max_turns", turns
