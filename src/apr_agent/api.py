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
    "load_trajectory",
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
