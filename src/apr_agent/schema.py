"""Data contract. DO NOT BREAK BACKWARDS COMPATIBILITY without bumping version."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _SchemaBase(BaseModel):
    """Schema base — `extra="ignore"` lets old readers accept newer trajectories."""
    model_config = ConfigDict(extra="ignore")


class BugSample(_SchemaBase):
    bug_id: str                        # e.g. "Math-12"
    project: str                       # e.g. "Math"
    bug_number: int
    buggy_checkout_dir: str
    trigger_tests: list[str]           # authoritative: `defects4j export -p tests.trigger`
    currently_failing: list[str]       # observed after checkout; may be superset of trigger_tests
    trigger_test_output: str
    defects4j_version: str             # e.g. "2.0.1" — frozen per bug for reproducibility
    d4j_subset: str | None = None      # e.g. "1.2" / "2.0" — academic slice label
    loc_hints: dict | None = None


class VerifyResult(_SchemaBase):
    all_passing: bool
    previously_failing_now_passing: list[str]
    newly_failing: list[str]
    patch_applied: bool
    test_exit_code: int
    runtime_s: float
    raw_output: str


class ToolCall(_SchemaBase):
    call_id: str
    tool_name: str
    tool_input: dict
    tool_output: str
    tool_meta: dict
    started_at: float
    ended_at: float
    is_error: bool


class Turn(_SchemaBase):
    turn_idx: int
    started_at: float
    ended_at: float
    request: dict                      # full body sent to LLM (sanitize secrets before dumping)
    response: dict                     # {"parsed": {...}, "raw": ...}; parsed is stable
    thinking: str | None = None
    usage: dict                        # MUST have prompt_tokens+completion_tokens (0 ok)
    tool_calls: list[ToolCall]


EventKind = Literal[
    "turn_start",
    "llm_response",
    "thinking",
    "text_block",
    "tool_call_start",
    "tool_call_end",
    "error",
    "turn_end",
    "verify_start",
    "verify_end",
]


class Event(_SchemaBase):
    event_id: int
    turn_idx: int
    at: float
    kind: EventKind
    payload: dict


TrajectoryStatus = Literal["running", "fixed", "failed", "aborted", "timeout", "error"]


class Trajectory(_SchemaBase):
    exp_id: str
    bug_id: str
    status: TrajectoryStatus
    bug_sample: BugSample
    turns: list[Turn]
    events: list[Event]
    final_patch: str
    verify: VerifyResult | None
    tool_registry: list[dict]
    meta: dict
