"""JSONL-based trajectory writer (file-backed, append-only, crash-safe)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from apr_agent.schema import BugSample, Event, Turn, VerifyResult

# Frozen contract. Bump MAJOR on rename/remove/semantic change; bump MINOR for
# additive fields. `extra="ignore"` plus the major check in api.load_trajectory
# together guarantee old readers still load newer trajectories within the same
# major. Changelog:
#   1.0 — initial M1 schema
#   1.1 — Turn.regression_summary (additive, optional); RunTestsTool meta
#         enriched with newly_failing / still_failing / now_passing
SCHEMA_VERSION = "1.1"


def bug_dir_for(data_root: Path | str, exp_id: str, bug_id: str) -> Path:
    return Path(data_root) / "trajectories" / exp_id / bug_id


def init_bug_dir(
    *,
    data_root: Path | str,
    exp_id: str,
    bug_sample: BugSample,
    tool_registry: list[dict],
    meta_extras: dict,
) -> Path:
    bug_dir = bug_dir_for(data_root, exp_id, bug_sample.bug_id)
    if bug_dir.exists():
        ts = int(time.time())
        trash = bug_dir.parent / f"{bug_dir.name}.trash-{ts}"
        bug_dir.rename(trash)

    bug_dir.mkdir(parents=True, exist_ok=False)
    (bug_dir / "raw").mkdir()

    (bug_dir / "bug_sample.json").write_text(
        json.dumps(bug_sample.model_dump(), ensure_ascii=False, indent=2)
    )
    (bug_dir / "tool_registry.json").write_text(
        json.dumps(tool_registry, ensure_ascii=False, indent=2)
    )

    meta = {
        "schema_version": SCHEMA_VERSION,
        "exp_id": exp_id,
        "bug_id": bug_sample.bug_id,
        "status": "running",
        "started_at": time.time(),
        **meta_extras,
    }
    _atomic_write_json(bug_dir / "meta.json", meta)

    (bug_dir / "turns.jsonl").touch()
    (bug_dir / "events.jsonl").touch()

    return bug_dir


def write_final_patch(bug_dir: Path, patch: str) -> None:
    (bug_dir / "final_patch.diff").write_text(patch)


def write_verify_result(bug_dir: Path, verify: VerifyResult) -> None:
    _atomic_write_json(bug_dir / "verify_result.json", verify.model_dump())


def finalize_meta(bug_dir: Path, *, status: str, extra: dict | None = None) -> None:
    meta_path = bug_dir / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["status"] = status
    meta["ended_at"] = time.time()
    if extra:
        meta.update(extra)
    _atomic_write_json(meta_path, meta)


def append_turn(bug_dir: Path, turn: Turn) -> None:
    _append_jsonl(bug_dir / "turns.jsonl", turn.model_dump())


def append_event(bug_dir: Path, event: Event) -> None:
    _append_jsonl(bug_dir / "events.jsonl", event.model_dump())


def _append_jsonl(path: Path, record: dict) -> None:
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def _atomic_write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, path)
