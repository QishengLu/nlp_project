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
                    err_msg = (
                        f"ERROR: tool arguments are not valid JSON ({parse_error}). "
                        f"Re-emit the tool call with strictly valid JSON in arguments."
                    )
                    out, meta, is_err = (
                        err_msg,
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
                    err = f"unknown tool {tool_name!r} — pick from the registered tools list"
                    out, meta, is_err = f"ERROR: {err}", {"error": err}, True
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
                regression_summary=_extract_regression_summary(tool_calls_record),
            )
            turns.append(turn)

            # Build messages for next turn (so the LLM sees its own prior outputs).
            #
            # IMPORTANT: rebuild tool_calls from the parsed `tool_calls_record`,
            # NOT from `resp.tool_calls` raw. Some providers (DashScope) reject
            # echoed tool_calls whose `arguments` aren't valid JSON. If the LLM
            # emitted malformed JSON we already recorded `tool_input={}` plus
            # an is_error ToolCall — re-serialize from that so the next turn's
            # assistant message is always well-formed.
            assistant_msg: dict = {"role": "assistant", "content": resp.content}
            if tool_calls_record:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tcr.call_id,
                        "type": "function",
                        "function": {
                            "name": tcr.tool_name,
                            "arguments": _json.dumps(tcr.tool_input, ensure_ascii=False),
                        },
                    }
                    for tcr in tool_calls_record
                ]
            messages.append(assistant_msg)
            for tcr in tool_calls_record:
                messages.append({
                    "role": "tool", "tool_call_id": tcr.call_id, "content": tcr.tool_output,
                })

            if terminated:
                return "finish", turns

        return "max_turns", turns


def _extract_regression_summary(tool_calls: list[ToolCall]) -> dict | None:
    """Lift the regression labels out of the last successful run_tests in this
    turn. Returns None if no run_tests fired (or only errored ones did).

    Schema 1.1+: surfaces `currently_failing/newly_failing/still_failing/now_passing`
    on the Turn so downstream filters can find "agent saw regression and reacted"
    moments without re-parsing each ToolCall.tool_meta.
    """
    for tc in reversed(tool_calls):
        if tc.tool_name != "run_tests" or tc.is_error:
            continue
        m = tc.tool_meta or {}
        if "newly_failing" not in m and "still_failing" not in m:
            return None  # pre-1.1 RunTestsTool, no labels available
        return {
            "currently_failing": list(m.get("currently_failing", [])),
            "newly_failing":     list(m.get("newly_failing", [])),
            "still_failing":     list(m.get("still_failing", [])),
            "now_passing":       list(m.get("now_passing", [])),
        }
    return None
