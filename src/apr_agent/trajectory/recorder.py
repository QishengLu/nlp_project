"""Runtime wrapper that owns the bug_dir and emits events/turns to the writer."""
from __future__ import annotations

import time
from pathlib import Path

from apr_agent.schema import BugSample, Event, EventKind, Turn, VerifyResult
from apr_agent.trajectory.writer_jsonl import (
    append_event,
    append_turn,
    finalize_meta,
    init_bug_dir,
    write_final_patch,
    write_verify_result,
)


class TrajectoryRecorder:
    """Live handle on a bug's trajectory dir. One instance per agent run."""

    def __init__(self, bug_dir: Path):
        self.bug_dir = bug_dir
        self._next_event_id = 0

    @classmethod
    def start(
        cls,
        *,
        data_root: Path | str,
        exp_id: str,
        bug_sample: BugSample,
        tool_registry: list[dict],
        meta_extras: dict,
    ) -> TrajectoryRecorder:
        bug_dir = init_bug_dir(
            data_root=data_root,
            exp_id=exp_id,
            bug_sample=bug_sample,
            tool_registry=tool_registry,
            meta_extras=meta_extras,
        )
        return cls(bug_dir)

    def emit(self, kind: EventKind, *, turn_idx: int, payload: dict) -> Event:
        ev = Event(
            event_id=self._next_event_id,
            turn_idx=turn_idx,
            at=time.time(),
            kind=kind,
            payload=payload,
        )
        self._next_event_id += 1
        append_event(self.bug_dir, ev)
        return ev

    def record_turn(self, turn: Turn) -> None:
        """Persist the turn first, then emit derived events.

        Order matters for crash recovery: if the worker dies mid-sequence, we want
        either (turn + partial events) or (no turn + no events) — never "events
        referencing a turn that was never written". Hence `append_turn` goes first.
        """
        append_turn(self.bug_dir, turn)
        stop_reason = None
        if isinstance(turn.response, dict):
            parsed = turn.response.get("parsed") or {}
            stop_reason = parsed.get("stop_reason", turn.response.get("stop_reason"))
        self.emit("llm_response", turn_idx=turn.turn_idx,
                  payload={"stop_reason": stop_reason})
        for tc in turn.tool_calls:
            self.emit("tool_call_start", turn_idx=turn.turn_idx,
                      payload={"call_id": tc.call_id, "tool_name": tc.tool_name,
                               "tool_input": tc.tool_input})
            self.emit("tool_call_end", turn_idx=turn.turn_idx,
                      payload={"call_id": tc.call_id, "is_error": tc.is_error,
                               "tool_meta": tc.tool_meta})
        self.emit("turn_end", turn_idx=turn.turn_idx, payload={})

    def write_patch(self, patch: str) -> None:
        write_final_patch(self.bug_dir, patch)

    def write_verify(self, verify: VerifyResult) -> None:
        write_verify_result(self.bug_dir, verify)

    def finalize(self, *, status: str, extra: dict | None = None) -> None:
        finalize_meta(self.bug_dir, status=status, extra=extra)
