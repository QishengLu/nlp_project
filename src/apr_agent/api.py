"""Public API — the stable contract for downstream consumers.

Downstream consumers (step-summarizer, small-model-trainer) should import ONLY
from this module or the package root. Internals (agent/, tools/, trajectory/)
are not guaranteed stable.
"""
from __future__ import annotations

import json
from pathlib import Path

from apr_agent.schema import BugSample, Event, Trajectory, Turn, VerifyResult
from apr_agent.trajectory.writer_jsonl import SCHEMA_VERSION, bug_dir_for

__all__ = [
    "Trajectory", "Turn", "Event", "VerifyResult", "BugSample",
    "load_trajectory", "iter_trajectories", "list_bugs", "list_experiments",
    "get_turns_as_messages",
    "SchemaVersionError",
]


class SchemaVersionError(RuntimeError):
    """Raised when an on-disk trajectory's schema_version has a different major than this library."""


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
