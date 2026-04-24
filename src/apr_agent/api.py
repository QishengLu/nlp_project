"""Public API — the stable contract for downstream consumers.

Downstream consumers (step-summarizer, small-model-trainer) should import ONLY
from this module or the package root. Internals (agent/, tools/, trajectory/)
are not guaranteed stable.
"""
from __future__ import annotations

import json
from pathlib import Path

from dataclasses import dataclass
from typing import Literal

from apr_agent.schema import BugSample, Event, Trajectory, Turn, VerifyResult
from apr_agent.trajectory.writer_jsonl import SCHEMA_VERSION, bug_dir_for

__all__ = [
    "Trajectory", "Turn", "Event", "VerifyResult", "BugSample",
    "load_trajectory", "iter_trajectories", "list_bugs", "list_experiments",
    "get_turns_as_messages", "get_events_stream",
    "get_trajectory_for_summarization",
    "get_experiment_summary", "ExperimentSummary",
    "write_decomposed_steps", "read_decomposed_steps",
    "SchemaVersionError",
]


class SchemaVersionError(RuntimeError):
    """Raised when on-disk schema_version has a different major than this library."""


def _check_schema_version(meta: dict, *, path: Path) -> None:
    got = meta.get("schema_version")
    if got is None:
        raise SchemaVersionError(
            f"{path}: meta.json missing schema_version. "
            f"This library expects schema_version={SCHEMA_VERSION}."
        )
    want_major = SCHEMA_VERSION.split(".")[0]
    got_major = str(got).split(".")[0]
    if got_major != want_major:
        raise SchemaVersionError(
            f"{path}: schema_version={got} (major {got_major}) incompatible with "
            f"library schema_version={SCHEMA_VERSION} (major {want_major}). "
            f"Bump the library or migrate the data."
        )


def load_trajectory(
    data_root: Path | str,
    exp_id: str,
    bug_id: str,
) -> Trajectory:
    """Load a complete trajectory from disk."""
    bug_dir = bug_dir_for(data_root, exp_id, bug_id)
    if not bug_dir.is_dir():
        raise FileNotFoundError(f"Trajectory not found: {bug_dir}")

    meta = json.loads((bug_dir / "meta.json").read_text())
    _check_schema_version(meta, path=bug_dir / "meta.json")
    bug_sample = BugSample.model_validate_json((bug_dir / "bug_sample.json").read_text())
    tool_registry = json.loads((bug_dir / "tool_registry.json").read_text())

    turns = [Turn.model_validate_json(line)
             for line in _read_jsonl_lines(bug_dir / "turns.jsonl")]
    events = [Event.model_validate_json(line)
              for line in _read_jsonl_lines(bug_dir / "events.jsonl")]

    verify = None
    vp = bug_dir / "verify_result.json"
    if vp.exists():
        verify = VerifyResult.model_validate_json(vp.read_text())

    fp = bug_dir / "final_patch.diff"
    final_patch = fp.read_text() if fp.exists() else ""

    return Trajectory(
        exp_id=exp_id,
        bug_id=bug_id,
        status=meta.get("status", "error"),
        bug_sample=bug_sample,
        turns=turns,
        events=events,
        final_patch=final_patch,
        verify=verify,
        tool_registry=tool_registry,
        meta=meta,
    )


def _read_jsonl_lines(path: Path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield line


def list_experiments(data_root: Path | str) -> list[str]:
    root = Path(data_root) / "trajectories"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def list_bugs(
    data_root: Path | str,
    exp_id: str,
    status_filter: set[str] | None = None,
) -> list[str]:
    exp_dir = Path(data_root) / "trajectories" / exp_id
    if not exp_dir.is_dir():
        return []
    out: list[str] = []
    for p in exp_dir.iterdir():
        if not p.is_dir() or ".trash-" in p.name:
            continue
        if status_filter is not None:
            meta_path = p / "meta.json"
            if not meta_path.exists():
                continue
            status = json.loads(meta_path.read_text()).get("status")
            if status not in status_filter:
                continue
        out.append(p.name)
    return sorted(out)


def iter_trajectories(
    data_root: Path | str,
    exp_id: str,
    *,
    only_fixed: bool = False,
    status_in: set[str] | None = None,
    lazy_load_events: bool = False,  # reserved for future use
):
    """Yield Trajectory objects for an experiment, filtered by status."""
    del lazy_load_events  # accepted for forward compat, not yet implemented
    if only_fixed:
        status_in = {"fixed"}
    for bug_id in list_bugs(data_root, exp_id, status_filter=status_in):
        yield load_trajectory(data_root, exp_id, bug_id)


def get_turns_as_messages(
    trajectory: Trajectory,
    *,
    include_thinking: bool = False,
    include_system: bool = True,
) -> list[dict]:
    """Convert a Trajectory into OpenAI chat-template messages for SFT.

    Structure:
      - system (from turn 0's request, if any)
      - user (from turn 0's request)
      - per-turn assistant message (+ optional tool_calls)
      - per-tool_call tool message
    """
    messages: list[dict] = []

    if trajectory.turns:
        seed_request_messages = trajectory.turns[0].request.get("messages", [])
        for m in seed_request_messages:
            if m.get("role") == "system" and not include_system:
                continue
            messages.append(m)

    for turn in trajectory.turns:
        # turn.response shape from AgentLoop is {"parsed": {"content": ..., ...},
        # "raw": ...}. Older hand-built trajectories may still have flat
        # {"content": ...}; prefer parsed but fall back.
        parsed = turn.response.get("parsed", {}) if isinstance(turn.response, dict) else {}
        content = parsed.get("content") if "content" in parsed else turn.response.get("content", "")
        content = content or ""
        if include_thinking and turn.thinking:
            content = f"<think>{turn.thinking}</think>\n{content}"

        assistant_msg: dict = {"role": "assistant", "content": content}
        if turn.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.call_id,
                    "type": "function",
                    "function": {
                        "name": tc.tool_name,
                        "arguments": json.dumps(tc.tool_input, ensure_ascii=False),
                    },
                }
                for tc in turn.tool_calls
            ]
        messages.append(assistant_msg)

        for tc in turn.tool_calls:
            messages.append({
                "role": "tool",
                "tool_call_id": tc.call_id,
                "content": tc.tool_output,
            })

    return messages


def get_events_stream(trajectory: Trajectory) -> list[Event]:
    """Return events in persistence order. Trivial today; here for forward compat."""
    return list(trajectory.events)


def get_trajectory_for_summarization(
    trajectory: Trajectory,
    *,
    format: Literal["messages", "narrative", "events"] = "messages",
):
    """Shape a trajectory for step-summarization prompts.

    - messages: OpenAI chat-template (thinking included; same as get_turns_as_messages)
    - narrative: single human-readable string with turn boundaries
    - events: flat event list (list[Event])
    """
    if format == "messages":
        return get_turns_as_messages(trajectory, include_thinking=True)
    if format == "events":
        return get_events_stream(trajectory)
    if format == "narrative":
        return _render_narrative(trajectory)
    raise ValueError(f"unknown format: {format}")


def _render_narrative(trajectory: Trajectory) -> str:
    lines: list[str] = []
    lines.append(f"# Bug {trajectory.bug_id}  status={trajectory.status}")
    lines.append(f"trigger_tests: {', '.join(trajectory.bug_sample.trigger_tests)}")
    lines.append("")
    for turn in trajectory.turns:
        lines.append(f"## Turn {turn.turn_idx}")
        if turn.thinking:
            lines.append(f"(thinking) {turn.thinking}")
        parsed = turn.response.get("parsed") if isinstance(turn.response, dict) else {}
        content = (parsed or {}).get("content") or turn.response.get("content", "")
        if content:
            lines.append(content)
        for tc in turn.tool_calls:
            lines.append(f"→ {tc.tool_name}({_short_args(tc.tool_input)})"
                         f"  is_error={tc.is_error}")
            if tc.tool_output:
                lines.append(f"   output: {tc.tool_output[:200]}"
                             + ("…" if len(tc.tool_output) > 200 else ""))
        lines.append("")
    return "\n".join(lines)


def _short_args(d: dict) -> str:
    parts = [f"{k}={_short_val(v)}" for k, v in d.items()]
    return ", ".join(parts)


def _short_val(v) -> str:
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else repr(v)
    return s if len(s) <= 40 else s[:37] + "..."


# --- experiment summary ---

@dataclass
class ExperimentSummary:
    exp_id: str
    total: int
    fixed: int
    failed: int
    running: int
    error: int
    timeout: int
    aborted: int
    fix_rate: float     # fixed / total, 0 if total==0
    bug_ids: list[str]


def get_experiment_summary(
    data_root: Path | str, exp_id: str,
) -> ExperimentSummary:
    exp_dir = Path(data_root) / "trajectories" / exp_id
    if not exp_dir.is_dir():
        return ExperimentSummary(exp_id=exp_id, total=0, fixed=0, failed=0, running=0,
                                 error=0, timeout=0, aborted=0, fix_rate=0.0, bug_ids=[])
    counts = {"fixed": 0, "failed": 0, "running": 0,
              "error": 0, "timeout": 0, "aborted": 0}
    bug_ids: list[str] = []
    for p in sorted(exp_dir.iterdir()):
        if not p.is_dir() or ".trash-" in p.name:
            continue
        meta_path = p / "meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        status = meta.get("status", "error")
        counts[status] = counts.get(status, 0) + 1
        bug_ids.append(p.name)
    total = sum(counts.values())
    fix_rate = counts["fixed"] / total if total else 0.0
    return ExperimentSummary(
        exp_id=exp_id, total=total, fix_rate=fix_rate,
        bug_ids=bug_ids, **counts,
    )


# --- downstream decomposition read/write ---

def write_decomposed_steps(
    data_root: Path | str, exp_id: str, bug_id: str, steps: list[dict],
) -> None:
    """Persist the step-summarizer's output alongside the trajectory.

    `steps` is whatever shape the summarizer defines; we don't validate it.
    File: <bug_dir>/decomposed_steps.json
    """
    bug_dir = bug_dir_for(data_root, exp_id, bug_id)
    if not bug_dir.is_dir():
        raise FileNotFoundError(f"Trajectory not found: {bug_dir}")
    (bug_dir / "decomposed_steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2)
    )


def read_decomposed_steps(
    data_root: Path | str, exp_id: str, bug_id: str,
) -> list[dict] | None:
    """Return the decomposed-steps output if present, else None."""
    bug_dir = bug_dir_for(data_root, exp_id, bug_id)
    fp = bug_dir / "decomposed_steps.json"
    if not fp.exists():
        return None
    return json.loads(fp.read_text())
