# APR Agent M1: Foundation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship the data contract + end-to-end fake trajectory pipeline so downstream teammates can consume a stable schema before Defects4J/Qwen are wired up.

**Architecture:** Subprocess-per-bug agent worker writing JSONL trajectories (turn + flat event streams), with a pydantic schema as the frozen contract. M1 uses a FakeLLMClient to prove the loop + writer + reader work without touching Defects4J or Qwen.

**Tech Stack:** Python 3.11, pydantic v2, openai SDK (M3, not yet), typer, pytest, hatchling, uv, ruff.

**Reference:** [docs/plans/2026-04-24-apr-agent-design.md](./2026-04-24-apr-agent-design.md) — the approved design doc.

**Out of scope (deferred to M2/M3):** real Defects4J integration, real Qwen client, real tools (read_file / replace_block / run_tests), orchestrator concurrency.

---

## Working conventions

- TDD: write the failing test → watch it fail → minimal implementation → watch it pass → commit.
- Run `uv run pytest` from repo root; `uv run ruff check .` before each commit.
- Commit after every task (small, atomic).
- Commit messages: `feat:`, `test:`, `chore:`, `docs:`, `refactor:` (Conventional Commits).
- Paths are always relative to `/home/nn/workspace/nlp_project/` unless noted.

---

## Task 1: Package skeleton + editable install

**Files:**
- Create: `pyproject.toml`
- Create: `src/apr_agent/__init__.py`
- Create: `src/apr_agent/py.typed` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `.gitignore`
- Create: `README.md`

**Step 1: Create `pyproject.toml`**

```toml
[project]
name = "apr-agent"
version = "0.1.0"
description = "Agent-driven APR trajectory producer for Defects4J"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.6",
    "typer>=0.12",
    "rich>=13.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.1",
    "ruff>=0.3",
    "mypy>=1.8",
]

[project.scripts]
apr-agent = "apr_agent.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/apr_agent"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B"]
```

**Step 2: Create `src/apr_agent/__init__.py`**

```python
"""apr-agent: Agent-driven APR trajectory producer."""
__version__ = "0.1.0"
```

**Step 3: Create `.gitignore`**

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.ruff_cache/
.mypy_cache/
.venv/

# Data
data/
scratch/
*.log

# Env
.env
```

**Step 4: Create minimal `README.md`**

```markdown
# apr-agent

Agent-driven APR trajectory producer for Defects4J. See [docs/plans/2026-04-24-apr-agent-design.md](./docs/plans/2026-04-24-apr-agent-design.md) for design.

## Install

    uv venv && source .venv/bin/activate
    uv pip install -e ".[dev]"

## Test

    uv run pytest
```

**Step 5: Create empty `tests/__init__.py` and `src/apr_agent/py.typed`**

```bash
touch tests/__init__.py src/apr_agent/py.typed
```

**Step 6: Create venv and install editable**

Run:
```bash
uv venv && uv pip install -e ".[dev]"
```
Expected: "Installed N packages" with no errors.

**Step 7: Verify import works**

Run:
```bash
uv run python -c "import apr_agent; print(apr_agent.__version__)"
```
Expected output: `0.1.0`

**Step 8: Commit**

```bash
git add pyproject.toml src/apr_agent/__init__.py src/apr_agent/py.typed tests/__init__.py .gitignore README.md
git commit -m "chore: bootstrap apr-agent package skeleton"
```

---

## Task 2: Schema — `BugSample` and `VerifyResult`

**Files:**
- Create: `src/apr_agent/schema.py`
- Create: `tests/test_schema.py`

**Step 1: Write the failing test — `tests/test_schema.py`**

```python
from apr_agent.schema import BugSample, VerifyResult


def test_bug_sample_roundtrip():
    s = BugSample(
        bug_id="Math-12",
        project="Math",
        bug_number=12,
        buggy_checkout_dir="/tmp/scratch/Math-12",
        trigger_tests=["org.apache.commons.math.TestFoo::bar"],
        currently_failing=["org.apache.commons.math.TestFoo::bar"],
        trigger_test_output="AssertionError: expected 1, got 2",
        defects4j_version="2.0.1",
    )
    dumped = s.model_dump()
    restored = BugSample.model_validate(dumped)
    assert restored == s
    assert restored.loc_hints is None
    assert restored.d4j_subset is None   # optional


def test_verify_result_defaults():
    v = VerifyResult(
        all_passing=True,
        previously_failing_now_passing=["t1"],
        newly_failing=[],
        patch_applied=True,
        test_exit_code=0,
        runtime_s=12.5,
        raw_output="",
    )
    assert v.all_passing is True


def test_schema_ignores_extra_fields():
    raw = {
        "bug_id": "Math-1",
        "project": "Math",
        "bug_number": 1,
        "buggy_checkout_dir": "/tmp/x",
        "trigger_tests": [],
        "currently_failing": [],
        "trigger_test_output": "",
        "defects4j_version": "2.0.1",
        "future_field_added_later": "ok",
    }
    parsed = BugSample.model_validate(raw)
    assert parsed.bug_id == "Math-1"
```

**Step 2: Run test, verify it fails**

Run: `uv run pytest tests/test_schema.py -v`
Expected: `ModuleNotFoundError: No module named 'apr_agent.schema'`

**Step 3: Write `src/apr_agent/schema.py` (minimal to pass these tests)**

```python
"""Data contract. DO NOT BREAK BACKWARDS COMPATIBILITY without bumping version."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _SchemaBase(BaseModel):
    """All schema models ignore unknown fields so downstream readers don't crash on newer trajectories."""
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
```

**Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_schema.py -v`
Expected: 3 passed.

**Step 5: Commit**

```bash
git add src/apr_agent/schema.py tests/test_schema.py
git commit -m "feat: BugSample and VerifyResult schema"
```

---

## Task 3: Schema — `ToolCall`, `Turn`, `Event`

**Files:**
- Modify: `src/apr_agent/schema.py`
- Modify: `tests/test_schema.py`

**Step 1: Add failing tests to `tests/test_schema.py`**

Append:

```python
from apr_agent.schema import Event, ToolCall, Turn


def test_tool_call_roundtrip():
    tc = ToolCall(
        call_id="c1",
        tool_name="read_file",
        tool_input={"path": "a.java", "start_line": 1, "end_line": 10},
        tool_output="... file contents ...",
        tool_meta={"exit_code": 0},
        started_at=1000.0,
        ended_at=1000.5,
        is_error=False,
    )
    assert ToolCall.model_validate(tc.model_dump()) == tc


def test_turn_has_tool_calls():
    t = Turn(
        turn_idx=0,
        started_at=1000.0,
        ended_at=1002.0,
        request={"messages": []},
        response={"content": "ok"},
        thinking=None,
        usage={"prompt_tokens": 10, "completion_tokens": 5},
        tool_calls=[],
    )
    assert t.turn_idx == 0
    assert t.tool_calls == []


def test_event_kind_validation():
    e = Event(
        event_id=0,
        turn_idx=0,
        at=1000.0,
        kind="turn_start",
        payload={},
    )
    assert e.kind == "turn_start"


def test_event_invalid_kind_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Event(event_id=0, turn_idx=0, at=0.0, kind="bogus", payload={})
```

**Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_schema.py -v`
Expected: 4 new tests fail with ImportError for ToolCall/Turn/Event.

**Step 3: Add to `src/apr_agent/schema.py`**

Append after `VerifyResult`:

```python
from typing import Literal


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
    request: dict
    response: dict
    thinking: str | None = None
    usage: dict
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
```

**Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_schema.py -v`
Expected: 7 passed.

**Step 5: Commit**

```bash
git add src/apr_agent/schema.py tests/test_schema.py
git commit -m "feat: ToolCall, Turn, Event schema"
```

---

## Task 4: Schema — `Trajectory`

**Files:**
- Modify: `src/apr_agent/schema.py`
- Modify: `tests/test_schema.py`

**Step 1: Add failing test**

Append to `tests/test_schema.py`:

```python
from apr_agent.schema import Trajectory


def _sample_bug():
    return BugSample(
        bug_id="Math-12", project="Math", bug_number=12,
        buggy_checkout_dir="/tmp/x", trigger_tests=[], currently_failing=[],
        trigger_test_output="", defects4j_version="2.0.1",
    )


def test_trajectory_minimal():
    t = Trajectory(
        exp_id="exp1",
        bug_id="Math-12",
        status="running",
        bug_sample=_sample_bug(),
        turns=[],
        events=[],
        final_patch="",
        verify=None,
        tool_registry=[],
        meta={},
    )
    assert t.status == "running"
    assert Trajectory.model_validate(t.model_dump()) == t


def test_trajectory_status_invalid():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Trajectory(
            exp_id="e", bug_id="b", status="bogus",
            bug_sample=_sample_bug(), turns=[], events=[],
            final_patch="", verify=None, tool_registry=[], meta={},
        )
```

**Step 2: Run, verify fail**

Run: `uv run pytest tests/test_schema.py -v -k trajectory`
Expected: 2 new tests fail with ImportError for Trajectory.

**Step 3: Add to `src/apr_agent/schema.py`**

Append:

```python
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
```

**Step 4: Run, verify pass**

Run: `uv run pytest tests/test_schema.py -v`
Expected: 9 passed total.

**Step 5: Commit**

```bash
git add src/apr_agent/schema.py tests/test_schema.py
git commit -m "feat: Trajectory schema"
```

---

## Task 5: JSONL writer — header/finalize/patch files

**Files:**
- Create: `src/apr_agent/trajectory/__init__.py` (empty)
- Create: `src/apr_agent/trajectory/writer_jsonl.py`
- Create: `tests/test_writer_jsonl.py`

**Step 1: Write failing test — `tests/test_writer_jsonl.py`**

```python
import json
from pathlib import Path

import pytest

from apr_agent.schema import BugSample, VerifyResult
from apr_agent.trajectory.writer_jsonl import (
    bug_dir_for,
    finalize_meta,
    init_bug_dir,
    write_final_patch,
    write_verify_result,
)


def _bug():
    return BugSample(
        bug_id="Math-12", project="Math", bug_number=12,
        buggy_checkout_dir="/tmp/x", trigger_tests=["t1"], currently_failing=["t1"],
        trigger_test_output="out", defects4j_version="2.0.1",
    )


def test_init_bug_dir_creates_files(tmp_path: Path):
    data_root = tmp_path / "data"
    bug_dir = init_bug_dir(
        data_root=data_root,
        exp_id="exp1",
        bug_sample=_bug(),
        tool_registry=[{"name": "read_file"}],
        meta_extras={"model_name": "qwen"},
    )
    assert bug_dir == bug_dir_for(data_root, "exp1", "Math-12")
    assert bug_dir.is_dir()
    assert (bug_dir / "bug_sample.json").exists()
    assert (bug_dir / "tool_registry.json").exists()
    meta = json.loads((bug_dir / "meta.json").read_text())
    assert meta["status"] == "running"
    assert meta["bug_id"] == "Math-12"
    assert meta["model_name"] == "qwen"
    assert meta["schema_version"] == "1.0"    # frozen contract version
    assert (bug_dir / "turns.jsonl").exists()
    assert (bug_dir / "events.jsonl").exists()


def test_init_bug_dir_moves_existing_to_trash(tmp_path: Path):
    data_root = tmp_path / "data"
    init_bug_dir(data_root=data_root, exp_id="exp1", bug_sample=_bug(),
                 tool_registry=[], meta_extras={})
    # Second call: pre-existing dir should be trashed
    init_bug_dir(data_root=data_root, exp_id="exp1", bug_sample=_bug(),
                 tool_registry=[], meta_extras={})
    exp_dir = data_root / "trajectories" / "exp1"
    trash_dirs = [p for p in exp_dir.iterdir() if p.name.startswith("Math-12.trash-")]
    assert len(trash_dirs) == 1


def test_write_final_patch_and_verify(tmp_path: Path):
    data_root = tmp_path / "data"
    bug_dir = init_bug_dir(data_root=data_root, exp_id="exp1", bug_sample=_bug(),
                           tool_registry=[], meta_extras={})
    write_final_patch(bug_dir, "--- a\n+++ b\n")
    v = VerifyResult(
        all_passing=True, previously_failing_now_passing=["t1"], newly_failing=[],
        patch_applied=True, test_exit_code=0, runtime_s=1.0, raw_output="",
    )
    write_verify_result(bug_dir, v)

    assert (bug_dir / "final_patch.diff").read_text() == "--- a\n+++ b\n"
    loaded = json.loads((bug_dir / "verify_result.json").read_text())
    assert loaded["all_passing"] is True


def test_finalize_meta_atomic(tmp_path: Path):
    data_root = tmp_path / "data"
    bug_dir = init_bug_dir(data_root=data_root, exp_id="exp1", bug_sample=_bug(),
                           tool_registry=[], meta_extras={})
    finalize_meta(bug_dir, status="fixed", extra={"duration_s": 42.0})
    meta = json.loads((bug_dir / "meta.json").read_text())
    assert meta["status"] == "fixed"
    assert meta["duration_s"] == 42.0
```

**Step 2: Run, verify fail**

Run: `uv run pytest tests/test_writer_jsonl.py -v`
Expected: ImportError for `apr_agent.trajectory.writer_jsonl`.

**Step 3: Create `src/apr_agent/trajectory/__init__.py`**

```python
```
(empty)

**Step 4: Create `src/apr_agent/trajectory/writer_jsonl.py`**

```python
"""JSONL-based trajectory writer (file-backed, append-only, crash-safe)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from apr_agent.schema import BugSample, VerifyResult

# Frozen contract version. Bump MAJOR on any rename/removal/semantic change;
# bump MINOR for additive changes. `extra="ignore"` does not protect against
# removed/renamed fields — the version is the authoritative guard.
SCHEMA_VERSION = "1.0"


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
    """Create the per-bug dir. If one exists, move it to a trash dir first.

    Writes: bug_sample.json, tool_registry.json, meta.json (status=running),
    and touches empty turns.jsonl / events.jsonl / raw/.
    """
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
        "schema_version": SCHEMA_VERSION,    # bump major when breaking downstream
        "exp_id": exp_id,
        "bug_id": bug_sample.bug_id,
        "status": "running",
        "started_at": time.time(),
        **meta_extras,
    }
    _atomic_write_json(bug_dir / "meta.json", meta)

    # Touch append-only files so later fsync/append is simple.
    (bug_dir / "turns.jsonl").touch()
    (bug_dir / "events.jsonl").touch()

    return bug_dir


def write_final_patch(bug_dir: Path, patch: str) -> None:
    (bug_dir / "final_patch.diff").write_text(patch)


def write_verify_result(bug_dir: Path, verify: VerifyResult) -> None:
    _atomic_write_json(bug_dir / "verify_result.json", verify.model_dump())


def finalize_meta(bug_dir: Path, *, status: str, extra: dict | None = None) -> None:
    """Atomic update of meta.json's final status and end-of-run fields."""
    meta_path = bug_dir / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["status"] = status
    meta["ended_at"] = time.time()
    if extra:
        meta.update(extra)
    _atomic_write_json(meta_path, meta)


def _atomic_write_json(path: Path, data) -> None:
    """Write JSON atomically via tmp + rename."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, path)
```

**Step 5: Run tests, verify they pass**

Run: `uv run pytest tests/test_writer_jsonl.py -v`
Expected: 4 passed.

**Step 6: Commit**

```bash
git add src/apr_agent/trajectory/__init__.py src/apr_agent/trajectory/writer_jsonl.py tests/test_writer_jsonl.py
git commit -m "feat: JSONL writer (init/finalize/patch/verify)"
```

---

## Task 6: JSONL writer — append turns and events

**Files:**
- Modify: `src/apr_agent/trajectory/writer_jsonl.py`
- Modify: `tests/test_writer_jsonl.py`

**Step 1: Add failing tests**

Append to `tests/test_writer_jsonl.py`:

```python
from apr_agent.schema import Event, Turn
from apr_agent.trajectory.writer_jsonl import append_event, append_turn


def test_append_turn_and_event(tmp_path: Path):
    data_root = tmp_path / "data"
    bug_dir = init_bug_dir(data_root=data_root, exp_id="exp1", bug_sample=_bug(),
                           tool_registry=[], meta_extras={})

    t0 = Turn(turn_idx=0, started_at=0, ended_at=1, request={}, response={},
              thinking=None, usage={}, tool_calls=[])
    t1 = Turn(turn_idx=1, started_at=1, ended_at=2, request={}, response={},
              thinking=None, usage={}, tool_calls=[])
    append_turn(bug_dir, t0)
    append_turn(bug_dir, t1)

    e0 = Event(event_id=0, turn_idx=0, at=0.0, kind="turn_start", payload={})
    e1 = Event(event_id=1, turn_idx=0, at=0.1, kind="llm_response", payload={})
    append_event(bug_dir, e0)
    append_event(bug_dir, e1)

    lines = (bug_dir / "turns.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["turn_idx"] == 0

    elines = (bug_dir / "events.jsonl").read_text().splitlines()
    assert len(elines) == 2
    assert json.loads(elines[1])["event_id"] == 1
```

**Step 2: Run, verify fail**

Run: `uv run pytest tests/test_writer_jsonl.py::test_append_turn_and_event -v`
Expected: ImportError for `append_turn` / `append_event`.

**Step 3: Add functions to `writer_jsonl.py`**

Append:

```python
from apr_agent.schema import Event, Turn


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
```

**Step 4: Run, verify pass**

Run: `uv run pytest tests/test_writer_jsonl.py -v`
Expected: 5 passed.

**Step 5: Commit**

```bash
git add src/apr_agent/trajectory/writer_jsonl.py tests/test_writer_jsonl.py
git commit -m "feat: append_turn and append_event to JSONL"
```

---

## Task 7: `api.py` — `load_trajectory`

**Files:**
- Create: `src/apr_agent/api.py`
- Create: `tests/test_api_read.py`

**Step 1: Write failing test — `tests/test_api_read.py`**

```python
from pathlib import Path

from apr_agent.api import load_trajectory
from apr_agent.schema import BugSample, Event, Turn, VerifyResult
from apr_agent.trajectory.writer_jsonl import (
    append_event, append_turn, finalize_meta,
    init_bug_dir, write_final_patch, write_verify_result,
)


def _seed_bug(tmp_path: Path, exp_id="exp1", bug_id="Math-12"):
    data_root = tmp_path / "data"
    bug = BugSample(bug_id=bug_id, project="Math", bug_number=12,
                    buggy_checkout_dir="/tmp/x", trigger_tests=["t1"],
                    currently_failing=["t1"], trigger_test_output="",
                    defects4j_version="2.0.1")
    bd = init_bug_dir(data_root=data_root, exp_id=exp_id, bug_sample=bug,
                      tool_registry=[{"name": "finish"}],
                      meta_extras={"model_name": "fake"})
    t = Turn(turn_idx=0, started_at=0, ended_at=1, request={}, response={},
             thinking="thinking text", usage={}, tool_calls=[])
    append_turn(bd, t)
    append_event(bd, Event(event_id=0, turn_idx=0, at=0, kind="turn_start", payload={}))
    append_event(bd, Event(event_id=1, turn_idx=0, at=1, kind="turn_end", payload={}))
    write_final_patch(bd, "--- a\n+++ b\n")
    write_verify_result(bd, VerifyResult(
        all_passing=True, previously_failing_now_passing=["t1"], newly_failing=[],
        patch_applied=True, test_exit_code=0, runtime_s=1.0, raw_output="",
    ))
    finalize_meta(bd, status="fixed", extra={"duration_s": 1.0})
    return data_root


def test_load_trajectory_roundtrip(tmp_path: Path):
    data_root = _seed_bug(tmp_path)
    tr = load_trajectory(data_root, "exp1", "Math-12")
    assert tr.bug_id == "Math-12"
    assert tr.status == "fixed"
    assert len(tr.turns) == 1
    assert tr.turns[0].thinking == "thinking text"
    assert len(tr.events) == 2
    assert tr.final_patch == "--- a\n+++ b\n"
    assert tr.verify is not None
    assert tr.verify.all_passing is True
    assert tr.tool_registry == [{"name": "finish"}]
    assert tr.meta["model_name"] == "fake"
    assert tr.meta["duration_s"] == 1.0
    assert tr.meta["schema_version"] == "1.0"


def test_load_trajectory_rejects_incompatible_schema_version(tmp_path: Path):
    import json as _json

    import pytest

    from apr_agent.api import SchemaVersionError

    data_root = _seed_bug(tmp_path)
    meta_path = data_root / "trajectories" / "exp1" / "Math-12" / "meta.json"
    meta = _json.loads(meta_path.read_text())
    meta["schema_version"] = "2.0"     # future major the library doesn't know
    meta_path.write_text(_json.dumps(meta))

    with pytest.raises(SchemaVersionError):
        load_trajectory(data_root, "exp1", "Math-12")
```

**Step 2: Run, verify fail**

Run: `uv run pytest tests/test_api_read.py -v`
Expected: ImportError for `apr_agent.api`.

**Step 3: Create `src/apr_agent/api.py`**

```python
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
]


class SchemaVersionError(RuntimeError):
    """Raised when an on-disk trajectory's schema_version has a different major than this library."""


def _check_schema_version(meta: dict, *, path: Path) -> None:
    got = meta.get("schema_version")
    if got is None:
        # Pre-1.0 trajectories (shouldn't exist post-M1). Be strict — force user to migrate.
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
```

**Step 4: Run, verify pass**

Run: `uv run pytest tests/test_api_read.py -v`
Expected: 2 passed (`test_load_trajectory_roundtrip`, `test_load_trajectory_rejects_incompatible_schema_version`).

**Step 5: Export from package root — edit `src/apr_agent/__init__.py`**

```python
"""apr-agent: Agent-driven APR trajectory producer."""
__version__ = "0.1.0"

from apr_agent.api import *  # noqa: F401, F403
```

**Step 6: Add test that package-root import works**

Append to `tests/test_api_read.py`:

```python
def test_package_root_exports():
    import apr_agent
    assert hasattr(apr_agent, "load_trajectory")
    assert hasattr(apr_agent, "Trajectory")
```

Run: `uv run pytest tests/test_api_read.py -v`
Expected: 3 passed.

**Step 7: Commit**

```bash
git add src/apr_agent/api.py src/apr_agent/__init__.py tests/test_api_read.py
git commit -m "feat: load_trajectory + schema_version guard + package-root re-export"
```

---

## Task 8: `api.py` — `iter_trajectories`, `list_bugs`, `list_experiments`

**Files:**
- Modify: `src/apr_agent/api.py`
- Modify: `tests/test_api_read.py`

**Step 1: Add failing tests**

Append to `tests/test_api_read.py`:

```python
from apr_agent.api import iter_trajectories, list_bugs, list_experiments


def test_iter_trajectories_only_fixed(tmp_path: Path):
    _seed_bug(tmp_path, exp_id="exp1", bug_id="Math-12")
    _seed_bug(tmp_path, exp_id="exp1", bug_id="Math-5")  # also fixed
    # Mark Math-5 as failed:
    from apr_agent.trajectory.writer_jsonl import finalize_meta, bug_dir_for
    finalize_meta(bug_dir_for(tmp_path / "data", "exp1", "Math-5"), status="failed")

    all_ids = {t.bug_id for t in iter_trajectories(tmp_path / "data", "exp1")}
    assert all_ids == {"Math-12", "Math-5"}

    fixed = {t.bug_id for t in iter_trajectories(tmp_path / "data", "exp1", only_fixed=True)}
    assert fixed == {"Math-12"}


def test_list_bugs_and_experiments(tmp_path: Path):
    _seed_bug(tmp_path, exp_id="exp1", bug_id="Math-12")
    _seed_bug(tmp_path, exp_id="exp2", bug_id="Lang-1")

    assert set(list_experiments(tmp_path / "data")) == {"exp1", "exp2"}
    assert list_bugs(tmp_path / "data", "exp1") == ["Math-12"]


def test_iter_trajectories_ignores_trash(tmp_path: Path):
    _seed_bug(tmp_path, exp_id="exp1", bug_id="Math-12")
    _seed_bug(tmp_path, exp_id="exp1", bug_id="Math-12")  # second call trashes first
    ids = [t.bug_id for t in iter_trajectories(tmp_path / "data", "exp1")]
    assert ids == ["Math-12"]
```

**Step 2: Run, verify fail**

Run: `uv run pytest tests/test_api_read.py -v`
Expected: 3 new tests fail with ImportError.

**Step 3: Add to `src/apr_agent/api.py`**

Append:

```python
from collections.abc import Iterator


def iter_trajectories(
    data_root: Path | str,
    exp_id: str,
    *,
    only_fixed: bool = False,
    status_in: set[str] | None = None,
) -> Iterator[Trajectory]:
    exp_dir = Path(data_root) / "trajectories" / exp_id
    if not exp_dir.is_dir():
        return
    for child in sorted(exp_dir.iterdir()):
        if not child.is_dir():
            continue
        if ".trash-" in child.name:
            continue
        if not (child / "meta.json").exists():
            continue
        tr = load_trajectory(data_root, exp_id, child.name)
        if only_fixed and tr.status != "fixed":
            continue
        if status_in is not None and tr.status not in status_in:
            continue
        yield tr


def list_bugs(
    data_root: Path | str,
    exp_id: str,
    *,
    status_filter: set[str] | None = None,
) -> list[str]:
    return [t.bug_id for t in iter_trajectories(data_root, exp_id, status_in=status_filter)]


def list_experiments(data_root: Path | str) -> list[str]:
    root = Path(data_root) / "trajectories"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())
```

Also extend `__all__`:

```python
__all__ = [
    "Trajectory", "Turn", "Event", "VerifyResult", "BugSample",
    "load_trajectory", "iter_trajectories", "list_bugs", "list_experiments",
]
```

**Step 4: Run, verify pass**

Run: `uv run pytest tests/test_api_read.py -v`
Expected: 5 passed.

**Step 5: Commit**

```bash
git add src/apr_agent/api.py tests/test_api_read.py
git commit -m "feat: iter_trajectories + list_bugs + list_experiments"
```

---

## Task 9: `get_turns_as_messages` — OpenAI chat-template export

**Files:**
- Modify: `src/apr_agent/api.py`
- Create: `tests/test_api_transforms.py`

**Step 1: Write failing test — `tests/test_api_transforms.py`**

```python
from pathlib import Path

from apr_agent.api import get_turns_as_messages, load_trajectory
from apr_agent.schema import BugSample, ToolCall, Turn
from apr_agent.trajectory.writer_jsonl import append_turn, finalize_meta, init_bug_dir


def _make_traj(tmp_path: Path, thinking: str | None = None):
    data_root = tmp_path / "data"
    bug = BugSample(bug_id="Math-1", project="Math", bug_number=1,
                    buggy_checkout_dir="/x", trigger_tests=[], currently_failing=[],
                    trigger_test_output="", defects4j_version="2.0.1")
    bd = init_bug_dir(data_root=data_root, exp_id="e", bug_sample=bug,
                      tool_registry=[], meta_extras={})
    t0 = Turn(
        turn_idx=0, started_at=0, ended_at=1,
        request={"messages": [
            {"role": "system", "content": "You are an APR agent."},
            {"role": "user", "content": "Fix Math-1."},
        ]},
        response={"content": "I'll read the file first."},
        thinking=thinking,
        usage={}, tool_calls=[
            ToolCall(call_id="c1", tool_name="read_file",
                     tool_input={"path": "Foo.java"},
                     tool_output="file contents",
                     tool_meta={}, started_at=0.1, ended_at=0.2, is_error=False),
        ],
    )
    t1 = Turn(
        turn_idx=1, started_at=1, ended_at=2,
        request={"messages": []},
        response={"content": "Done."},
        thinking=None, usage={}, tool_calls=[],
    )
    append_turn(bd, t0)
    append_turn(bd, t1)
    finalize_meta(bd, status="fixed")
    return load_trajectory(data_root, "e", "Math-1")


def test_get_turns_as_messages_basic(tmp_path: Path):
    tr = _make_traj(tmp_path)
    msgs = get_turns_as_messages(tr)

    # Expect: system, user, assistant (with tool_calls), tool, assistant
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool", "assistant"]
    assert msgs[0]["content"] == "You are an APR agent."
    assert msgs[2]["content"] == "I'll read the file first."
    assert msgs[2]["tool_calls"][0]["function"]["name"] == "read_file"
    assert msgs[3]["tool_call_id"] == "c1"
    assert msgs[3]["content"] == "file contents"
    assert msgs[4]["content"] == "Done."


def test_get_turns_as_messages_thinking_excluded_by_default(tmp_path: Path):
    tr = _make_traj(tmp_path, thinking="internal thought")
    msgs = get_turns_as_messages(tr, include_thinking=False)
    assert "<think>" not in msgs[2]["content"]


def test_get_turns_as_messages_thinking_included(tmp_path: Path):
    tr = _make_traj(tmp_path, thinking="internal thought")
    msgs = get_turns_as_messages(tr, include_thinking=True)
    assert "<think>internal thought</think>" in msgs[2]["content"]


def test_get_turns_as_messages_no_system(tmp_path: Path):
    tr = _make_traj(tmp_path)
    msgs = get_turns_as_messages(tr, include_system=False)
    assert msgs[0]["role"] == "user"
```

**Step 2: Run, verify fail**

Run: `uv run pytest tests/test_api_transforms.py -v`
Expected: ImportError for `get_turns_as_messages`.

**Step 3: Add to `src/apr_agent/api.py`**

Append:

```python
import json as _json


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
                        "arguments": _json.dumps(tc.tool_input, ensure_ascii=False),
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
```

Extend `__all__`:

```python
__all__ = [
    "Trajectory", "Turn", "Event", "VerifyResult", "BugSample",
    "load_trajectory", "iter_trajectories", "list_bugs", "list_experiments",
    "get_turns_as_messages",
]
```

**Step 4: Run, verify pass**

Run: `uv run pytest tests/test_api_transforms.py -v`
Expected: 4 passed.

**Step 5: Commit**

```bash
git add src/apr_agent/api.py tests/test_api_transforms.py
git commit -m "feat: get_turns_as_messages (OpenAI chat-template export)"
```

---

## Task 10: `TrajectoryRecorder` — runtime wrapper over writer

**Files:**
- Create: `src/apr_agent/trajectory/recorder.py`
- Create: `tests/test_recorder.py`

**Step 1: Write failing test — `tests/test_recorder.py`**

```python
from pathlib import Path

from apr_agent.schema import BugSample, ToolCall, Turn
from apr_agent.trajectory.recorder import TrajectoryRecorder


def _bug():
    return BugSample(bug_id="Math-12", project="Math", bug_number=12,
                     buggy_checkout_dir="/tmp/x", trigger_tests=[], currently_failing=[],
                     trigger_test_output="", defects4j_version="2.0.1")


def test_recorder_full_flow(tmp_path: Path):
    r = TrajectoryRecorder.start(
        data_root=tmp_path / "data",
        exp_id="e",
        bug_sample=_bug(),
        tool_registry=[{"name": "finish"}],
        meta_extras={"model_name": "fake"},
    )
    # Emit an event directly:
    r.emit("turn_start", turn_idx=0, payload={"msg": "hi"})
    # Record a turn (should auto-emit llm_response + tool_call_* + turn_end events):
    r.record_turn(Turn(
        turn_idx=0, started_at=0, ended_at=1,
        request={}, response={"content": "ok"},
        thinking=None, usage={},
        tool_calls=[ToolCall(call_id="c1", tool_name="finish",
                             tool_input={"rationale": "done"}, tool_output="",
                             tool_meta={}, started_at=0, ended_at=0.1, is_error=False)],
    ))
    r.finalize(status="fixed", extra={"duration_s": 1.0})

    # Validate disk state via load_trajectory
    from apr_agent.api import load_trajectory
    tr = load_trajectory(tmp_path / "data", "e", "Math-12")
    assert tr.status == "fixed"
    assert len(tr.turns) == 1
    # Expect: our manual turn_start + auto llm_response + auto tool_call_start +
    # auto tool_call_end + auto turn_end = 5 events
    assert len(tr.events) == 5
    assert tr.events[0].kind == "turn_start"
    assert tr.events[1].kind == "llm_response"
    assert tr.events[-1].kind == "turn_end"


def test_recorder_event_ids_are_monotonic(tmp_path: Path):
    r = TrajectoryRecorder.start(
        data_root=tmp_path / "data",
        exp_id="e", bug_sample=_bug(),
        tool_registry=[], meta_extras={},
    )
    r.emit("turn_start", turn_idx=0, payload={})
    r.emit("turn_end", turn_idx=0, payload={})
    r.finalize(status="aborted")

    from apr_agent.api import load_trajectory
    tr = load_trajectory(tmp_path / "data", "e", "Math-12")
    ids = [e.event_id for e in tr.events]
    assert ids == sorted(ids)
    assert ids == list(range(len(ids)))
```

**Step 2: Run, verify fail**

Run: `uv run pytest tests/test_recorder.py -v`
Expected: ImportError for `apr_agent.trajectory.recorder`.

**Step 3: Create `src/apr_agent/trajectory/recorder.py`**

```python
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
    ) -> "TrajectoryRecorder":
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
        self.emit("llm_response", turn_idx=turn.turn_idx,
                  payload={"stop_reason": turn.response.get("parsed", {}).get("stop_reason")
                                           if "parsed" in turn.response
                                           else turn.response.get("stop_reason")})
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
```

**Step 4: Run, verify pass**

Run: `uv run pytest tests/test_recorder.py -v`
Expected: 2 passed.

**Step 5: Commit**

```bash
git add src/apr_agent/trajectory/recorder.py tests/test_recorder.py
git commit -m "feat: TrajectoryRecorder runtime wrapper"
```

---

## Task 11: Tool registry + `finish` stub tool

**Files:**
- Create: `src/apr_agent/tools/__init__.py` (empty)
- Create: `src/apr_agent/tools/registry.py`
- Create: `src/apr_agent/tools/finish.py`
- Create: `tests/test_tools_registry.py`

**Step 1: Write failing test — `tests/test_tools_registry.py`**

```python
import pytest

from apr_agent.tools.finish import FinishTool
from apr_agent.tools.registry import Tool, ToolRegistry


def test_registry_register_and_get():
    reg = ToolRegistry()
    reg.register(FinishTool())
    assert reg.get("finish").name == "finish"
    schemas = reg.openai_schemas()
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "finish"


def test_registry_rejects_duplicate():
    reg = ToolRegistry()
    reg.register(FinishTool())
    with pytest.raises(ValueError):
        reg.register(FinishTool())


def test_finish_tool_returns_done_marker():
    tool = FinishTool()
    result = tool.invoke({"rationale": "I fixed it."})
    assert result.is_error is False
    assert result.output == ""
    assert result.meta == {"rationale": "I fixed it."}
    assert tool.terminates_loop is True


def test_tool_abstract_contract():
    # A Tool must expose name, description, parameters, terminates_loop, invoke
    t = FinishTool()
    assert isinstance(t.name, str)
    assert isinstance(t.description, str)
    assert isinstance(t.parameters, dict)
```

**Step 2: Run, verify fail**

Run: `uv run pytest tests/test_tools_registry.py -v`
Expected: ImportError.

**Step 3: Create `src/apr_agent/tools/__init__.py`** (empty file).

**Step 4: Create `src/apr_agent/tools/registry.py`**

```python
"""Tool registry + Tool base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ToolResult:
    output: str          # stringified, goes back to the LLM
    meta: dict           # structured details (exit_code, file_path, etc.)
    is_error: bool = False


class Tool(ABC):
    """Abstract base for agent tools."""

    terminates_loop: bool = False  # True iff this tool ends the agent run (e.g. finish)

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """JSON Schema for the tool's inputs."""

    @abstractmethod
    def invoke(self, arguments: dict) -> ToolResult: ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def openai_schemas(self) -> list[dict]:
        """Return OpenAI function-calling tool schemas for all registered tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]
```

**Step 5: Create `src/apr_agent/tools/finish.py`**

```python
"""finish tool — declares the agent is done; orchestrator runs verify after."""
from __future__ import annotations

from apr_agent.tools.registry import Tool, ToolResult


class FinishTool(Tool):
    terminates_loop = True

    @property
    def name(self) -> str:
        return "finish"

    @property
    def description(self) -> str:
        return (
            "Declare that the bug is fixed. Provide a short rationale describing "
            "what was changed and why."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "rationale": {
                    "type": "string",
                    "description": "Short rationale for the fix.",
                },
            },
            "required": ["rationale"],
        }

    def invoke(self, arguments: dict) -> ToolResult:
        return ToolResult(output="", meta={"rationale": arguments.get("rationale", "")})
```

**Step 6: Run, verify pass**

Run: `uv run pytest tests/test_tools_registry.py -v`
Expected: 4 passed.

**Step 7: Commit**

```bash
git add src/apr_agent/tools/__init__.py src/apr_agent/tools/registry.py src/apr_agent/tools/finish.py tests/test_tools_registry.py
git commit -m "feat: ToolRegistry + FinishTool"
```

---

## Task 12: `FakeLLMClient` — scriptable fake for testing the loop

**Files:**
- Create: `src/apr_agent/llm/__init__.py` (empty)
- Create: `src/apr_agent/llm/client.py`
- Create: `src/apr_agent/llm/fake.py`
- Create: `tests/test_fake_llm.py`

**Step 1: Write failing test — `tests/test_fake_llm.py`**

```python
from apr_agent.llm.fake import FakeLLMClient, ScriptedResponse


def test_fake_llm_plays_back_scripted_responses():
    client = FakeLLMClient(
        script=[
            ScriptedResponse(content="thinking about it", tool_calls=[
                {"id": "c1", "name": "finish", "arguments": {"rationale": "ok"}}
            ]),
        ]
    )
    r = client.chat(messages=[{"role": "user", "content": "fix Math-1"}], tools=[])
    assert r.content == "thinking about it"
    assert r.tool_calls[0]["function"]["name"] == "finish"
    assert r.usage["prompt_tokens"] == 0  # fake uses zero tokens


def test_fake_llm_exhaustion_raises():
    client = FakeLLMClient(script=[])
    import pytest
    with pytest.raises(RuntimeError):
        client.chat(messages=[], tools=[])


def test_fake_llm_usage_has_required_keys():
    """Contract: every Turn.usage MUST have prompt_tokens and completion_tokens,
    filled with 0 if unknown. Downstream cost/attribution code can rely on this."""
    client = FakeLLMClient(script=[ScriptedResponse(content="x")])
    r = client.chat(messages=[], tools=[])
    assert "prompt_tokens" in r.usage
    assert "completion_tokens" in r.usage
    assert isinstance(r.usage["prompt_tokens"], int)
    assert isinstance(r.usage["completion_tokens"], int)
```

**Step 2: Run, verify fail**

Run: `uv run pytest tests/test_fake_llm.py -v`
Expected: ImportError.

**Step 3: Create `src/apr_agent/llm/__init__.py`** (empty file).

**Step 4: Create `src/apr_agent/llm/client.py`** (interface shared by real + fake)

```python
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
```

**Step 5: Create `src/apr_agent/llm/fake.py`**

```python
"""Scripted fake LLM client for tests."""
from __future__ import annotations

import json as _json
from dataclasses import dataclass, field

from apr_agent.llm.client import ChatResponse


@dataclass
class ScriptedResponse:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)  # [{id, name, arguments}]
    stop_reason: str = "stop"
    thinking: str | None = None


class FakeLLMClient:
    def __init__(self, script: list[ScriptedResponse]):
        self._script = list(script)
        self._idx = 0

    def chat(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> ChatResponse:
        if self._idx >= len(self._script):
            raise RuntimeError("FakeLLMClient script exhausted")
        step = self._script[self._idx]
        self._idx += 1

        oa_tool_calls = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": _json.dumps(tc["arguments"], ensure_ascii=False),
                },
            }
            for tc in step.tool_calls
        ]

        return ChatResponse(
            content=step.content,
            tool_calls=oa_tool_calls,
            stop_reason=step.stop_reason,
            thinking=step.thinking,
            usage={"prompt_tokens": 0, "completion_tokens": 0},
            raw={"content": step.content, "tool_calls": oa_tool_calls,
                 "stop_reason": step.stop_reason, "thinking": step.thinking},
        )
```

**Step 6: Run, verify pass**

Run: `uv run pytest tests/test_fake_llm.py -v`
Expected: 3 passed.

**Step 7: Commit**

```bash
git add src/apr_agent/llm/__init__.py src/apr_agent/llm/client.py src/apr_agent/llm/fake.py tests/test_fake_llm.py
git commit -m "feat: LLMClient Protocol + FakeLLMClient"
```

---

## Task 13: Agent loop — tool-use while loop

**Files:**
- Create: `src/apr_agent/agent/__init__.py` (empty)
- Create: `src/apr_agent/agent/loop.py`
- Create: `tests/test_agent_loop.py`

**Step 1: Write failing test — `tests/test_agent_loop.py`**

```python
import json as _json
from pathlib import Path

from apr_agent.agent.loop import AgentLoop, AgentConfig
from apr_agent.llm.fake import FakeLLMClient, ScriptedResponse
from apr_agent.schema import BugSample
from apr_agent.tools.finish import FinishTool
from apr_agent.tools.registry import ToolRegistry


def _bug():
    return BugSample(bug_id="Math-1", project="Math", bug_number=1,
                     buggy_checkout_dir="/tmp/x", trigger_tests=[], currently_failing=[],
                     trigger_test_output="", defects4j_version="2.0.1")


def test_loop_terminates_on_finish(tmp_path: Path):
    fake = FakeLLMClient(script=[
        ScriptedResponse(content="I'll call finish.", tool_calls=[
            {"id": "c1", "name": "finish", "arguments": {"rationale": "done"}},
        ]),
    ])
    reg = ToolRegistry()
    reg.register(FinishTool())

    loop = AgentLoop(
        llm=fake,
        tools=reg,
        config=AgentConfig(max_turns=5, system_prompt="You are an APR agent.",
                           user_prompt_template="Fix {bug_id}."),
    )
    stop_reason, turns = loop.run(_bug())

    assert stop_reason == "finish"
    assert len(turns) == 1
    assert turns[0].tool_calls[0].tool_name == "finish"
    # Arguments survived the round-trip:
    assert turns[0].tool_calls[0].tool_input == {"rationale": "done"}


def test_loop_respects_max_turns(tmp_path: Path):
    # Script keeps calling a non-terminating no-op (we simulate by re-using finish but mark it non-terminating)
    fake = FakeLLMClient(script=[
        ScriptedResponse(content="a"),
        ScriptedResponse(content="b"),
        ScriptedResponse(content="c"),
    ])
    reg = ToolRegistry()
    # No terminating tool → loop runs until max_turns
    loop = AgentLoop(
        llm=fake,
        tools=reg,
        config=AgentConfig(max_turns=2, system_prompt="sys", user_prompt_template="fix {bug_id}"),
    )
    stop_reason, turns = loop.run(_bug())
    assert stop_reason == "max_turns"
    assert len(turns) == 2


def test_loop_survives_malformed_tool_arguments(tmp_path: Path):
    """Small models frequently emit invalid JSON in tool_calls. The loop must
    record the failure as is_error=True and keep going, so the LLM sees its own
    mistake in the next turn and can self-correct."""
    from apr_agent.llm.client import ChatResponse

    class BadJSONClient:
        def __init__(self):
            self._calls = 0

        def chat(self, *, messages, tools, temperature=0.2, max_tokens=4096):
            self._calls += 1
            if self._calls == 1:
                # First turn: malformed JSON arguments
                return ChatResponse(
                    content="let me fix it",
                    tool_calls=[{"id": "c1", "type": "function",
                                 "function": {"name": "finish",
                                              "arguments": "{not valid json"}}],
                    stop_reason="tool_calls", thinking=None,
                    usage={"prompt_tokens": 0, "completion_tokens": 0},
                    raw={},
                )
            # Second turn: valid JSON, terminates
            return ChatResponse(
                content="retry", tool_calls=[{"id": "c2", "type": "function",
                                              "function": {"name": "finish",
                                                           "arguments": '{"rationale":"ok"}'}}],
                stop_reason="tool_calls", thinking=None,
                usage={"prompt_tokens": 0, "completion_tokens": 0},
                raw={},
            )

    reg = ToolRegistry()
    reg.register(FinishTool())
    loop = AgentLoop(
        llm=BadJSONClient(), tools=reg,
        config=AgentConfig(max_turns=5, system_prompt="s", user_prompt_template="f {bug_id}"),
    )
    stop_reason, turns = loop.run(_bug())
    assert stop_reason == "finish"
    assert len(turns) == 2
    # First turn: is_error=True, parse_error recorded, loop did not crash
    bad = turns[0].tool_calls[0]
    assert bad.is_error is True
    assert bad.tool_meta["error"] == "malformed_tool_arguments"
    assert "parse_error" in bad.tool_meta
    # Second turn: succeeded
    assert turns[1].tool_calls[0].is_error is False
```

**Step 2: Run, verify fail**

Run: `uv run pytest tests/test_agent_loop.py -v`
Expected: ImportError.

**Step 3: Create `src/apr_agent/agent/__init__.py`** (empty).

**Step 4: Create `src/apr_agent/agent/loop.py`**

```python
"""Tool-use while loop. LLM-agnostic; takes an LLMClient + ToolRegistry."""
from __future__ import annotations

import json as _json
import time
from dataclasses import dataclass

from apr_agent.llm.client import LLMClient
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

            # Execute tool calls (if any).
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
                        {"error": "malformed_tool_arguments", "parse_error": parse_error,
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
            # Keep parsed and raw response cleanly separated. `**resp.raw` used to be
            # spread after `content`/`tool_calls`/`stop_reason`, silently clobbering the
            # parsed view with whatever shape the provider happened to return.
            turn = Turn(
                turn_idx=turn_idx,
                started_at=started, ended_at=ended,
                request=request_body,
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
```

**Step 5: Run, verify pass**

Run: `uv run pytest tests/test_agent_loop.py -v`
Expected: 3 passed.

**Step 6: Commit**

```bash
git add src/apr_agent/agent/__init__.py src/apr_agent/agent/loop.py tests/test_agent_loop.py
git commit -m "feat: AgentLoop tool-use while-loop with malformed-JSON recovery"
```

---

## Task 14: End-to-end integration — Fake agent produces readable trajectory

**Files:**
- Create: `tests/test_e2e_fake.py`

**Step 1: Write the integration test — `tests/test_e2e_fake.py`**

```python
"""End-to-end: FakeLLM + AgentLoop + TrajectoryRecorder → on-disk trajectory → read back."""
from pathlib import Path

from apr_agent.agent.loop import AgentConfig, AgentLoop
from apr_agent.api import get_turns_as_messages, iter_trajectories, load_trajectory
from apr_agent.llm.fake import FakeLLMClient, ScriptedResponse
from apr_agent.schema import BugSample
from apr_agent.tools.finish import FinishTool
from apr_agent.tools.registry import ToolRegistry
from apr_agent.trajectory.recorder import TrajectoryRecorder


def test_fake_e2e_produces_loadable_trajectory(tmp_path: Path):
    bug = BugSample(
        bug_id="Math-12", project="Math", bug_number=12,
        buggy_checkout_dir="/tmp/x",
        trigger_tests=["org.apache.commons.math.TestFoo::bar"],
        currently_failing=["org.apache.commons.math.TestFoo::bar"],
        trigger_test_output="AssertionError",
        defects4j_version="2.0.1",
    )

    # 1. Build fake LLM, tools, recorder
    fake = FakeLLMClient(script=[
        ScriptedResponse(
            content="I'll finish now.", thinking="let me think",
            tool_calls=[{"id": "c1", "name": "finish",
                         "arguments": {"rationale": "fake fix"}}],
        ),
    ])
    reg = ToolRegistry()
    reg.register(FinishTool())

    rec = TrajectoryRecorder.start(
        data_root=tmp_path / "data", exp_id="fake-exp-1",
        bug_sample=bug,
        tool_registry=reg.openai_schemas(),
        meta_extras={"model_name": "fake-llm", "apr_agent_version": "0.1.0"},
    )

    # 2. Run loop
    loop = AgentLoop(
        llm=fake, tools=reg,
        config=AgentConfig(max_turns=5,
                           system_prompt="You are an APR agent.",
                           user_prompt_template="Fix {bug_id}. Trigger: {trigger_tests}"),
    )
    stop_reason, turns = loop.run(bug)
    for turn in turns:
        rec.record_turn(turn)

    # 3. Finalize (in M1 we don't have real verify; set status based on stop_reason)
    rec.finalize(status="fixed" if stop_reason == "finish" else "failed",
                 extra={"stop_reason": stop_reason, "duration_s": 0.0})

    # 4. Read back via public API
    tr = load_trajectory(tmp_path / "data", "fake-exp-1", "Math-12")
    assert tr.status == "fixed"
    assert len(tr.turns) == 1
    assert tr.turns[0].tool_calls[0].tool_name == "finish"
    assert tr.turns[0].thinking == "let me think"
    assert tr.meta["model_name"] == "fake-llm"
    # 4 derived events: llm_response + tool_call_start + tool_call_end + turn_end
    # (no manual turn_start in this flow)
    assert len(tr.events) == 4

    # 5. Verify iter_trajectories + get_turns_as_messages work on the output
    fixed = list(iter_trajectories(tmp_path / "data", "fake-exp-1", only_fixed=True))
    assert len(fixed) == 1

    msgs = get_turns_as_messages(tr, include_thinking=True)
    roles = [m["role"] for m in msgs]
    assert roles == ["system", "user", "assistant", "tool"]
    assert "<think>let me think</think>" in msgs[2]["content"]
    assert msgs[3]["content"] == ""  # finish tool returns empty output
```

**Step 2: Run, verify pass**

Run: `uv run pytest tests/test_e2e_fake.py -v`
Expected: 1 passed.

If it fails, debug — this test is the whole point of M1. Read the error, diagnose, fix the offending module, re-run.

**Step 3: Commit**

```bash
git add tests/test_e2e_fake.py
git commit -m "test: end-to-end fake-agent trajectory integration"
```

---

## Task 15: CLI stub — `apr-agent --help` works

**Files:**
- Create: `src/apr_agent/cli.py`
- Create: `tests/test_cli.py`

**Step 1: Write failing test — `tests/test_cli.py`**

```python
import subprocess


def test_cli_help_shows_commands():
    r = subprocess.run(["apr-agent", "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "run-batch" in r.stdout
```

**Step 2: Run, verify fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: ModuleNotFoundError or "No such command" — because `cli.py` doesn't exist.

**Step 3: Create `src/apr_agent/cli.py`**

```python
"""CLI entry point. M1 only has a stub run-batch that prints config."""
from __future__ import annotations

import typer

app = typer.Typer(help="apr-agent CLI")


@app.command()
def run_batch(
    config: str = typer.Option(..., "--config", help="Path to bugs.yaml"),
    exp_id: str = typer.Option(..., "--exp-id"),
    data_root: str = typer.Option("data", "--data-root"),
    concurrency: int = typer.Option(1, "--concurrency"),
) -> None:
    """Run a batch of bugs (M1 stub — prints resolved config, does not execute)."""
    typer.echo(f"config={config} exp_id={exp_id} data_root={data_root} concurrency={concurrency}")
    typer.echo("[stub] orchestrator not yet implemented (see M4).")


if __name__ == "__main__":
    app()
```

**Step 4: Re-install package to pick up the new entry point**

Run:
```bash
uv pip install -e .
```

**Step 5: Run test, verify pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 1 passed.

Manually verify:
```bash
uv run apr-agent --help
```
Expected: typer usage text including `run-batch`.

**Step 6: Commit**

```bash
git add src/apr_agent/cli.py tests/test_cli.py
git commit -m "feat: CLI stub (apr-agent run-batch)"
```

---

## Task 16: Contract test — simulated downstream consumer

**Files:**
- Create: `tests/test_contract_downstream.py`

**Step 1: Write the contract test — `tests/test_contract_downstream.py`**

This test documents the *exact* API surface downstream teammates are supposed to use, and exercises it end-to-end. If this test breaks, the contract breaks.

```python
"""Contract test — what the two downstream teammates will actually call.

If you change anything here, you're changing the public contract.
Bump version and coordinate with downstream.
"""
from pathlib import Path

import apr_agent
from apr_agent import (
    BugSample, Event, Trajectory, Turn, VerifyResult,
    load_trajectory, iter_trajectories, list_bugs, list_experiments,
    get_turns_as_messages,
)


def _seed_minimal(tmp_path: Path):
    """Reuse the fake e2e helper to produce a real trajectory."""
    from apr_agent.agent.loop import AgentConfig, AgentLoop
    from apr_agent.llm.fake import FakeLLMClient, ScriptedResponse
    from apr_agent.tools.finish import FinishTool
    from apr_agent.tools.registry import ToolRegistry
    from apr_agent.trajectory.recorder import TrajectoryRecorder

    bug = BugSample(bug_id="B-1", project="B", bug_number=1,
                    buggy_checkout_dir="/tmp/x", trigger_tests=[], currently_failing=[],
                    trigger_test_output="", defects4j_version="2.0.1")
    fake = FakeLLMClient(script=[ScriptedResponse(content="done",
        tool_calls=[{"id": "c1", "name": "finish", "arguments": {"rationale": "r"}}])])
    reg = ToolRegistry(); reg.register(FinishTool())
    rec = TrajectoryRecorder.start(data_root=tmp_path / "data", exp_id="exp",
                                   bug_sample=bug, tool_registry=reg.openai_schemas(),
                                   meta_extras={"model_name": "fake"})
    loop = AgentLoop(llm=fake, tools=reg, config=AgentConfig(
        max_turns=3, system_prompt="s", user_prompt_template="fix {bug_id}"))
    _, turns = loop.run(bug)
    for t in turns:
        rec.record_turn(t)
    rec.finalize(status="fixed")


def test_summarizer_flow(tmp_path: Path):
    """Simulates the '总结同学' workflow."""
    _seed_minimal(tmp_path)
    for tr in iter_trajectories(tmp_path / "data", "exp", only_fixed=True):
        assert isinstance(tr, Trajectory)
        assert tr.turns  # non-empty
        # They can walk events for fine-grained timeline:
        for ev in tr.events:
            assert isinstance(ev, Event)
        # ...and hand the messages to their own LLM for step decomposition
        msgs = get_turns_as_messages(tr, include_thinking=True)
        assert msgs[0]["role"] in {"system", "user"}


def test_small_model_trainer_flow(tmp_path: Path):
    """Simulates the '小模型同学' workflow — build SFT records."""
    _seed_minimal(tmp_path)
    sft_records = []
    for bug_id in list_bugs(tmp_path / "data", "exp", status_filter={"fixed"}):
        tr = load_trajectory(tmp_path / "data", "exp", bug_id)
        sft_records.append({
            "bug_id": tr.bug_id,
            "messages": get_turns_as_messages(tr, include_thinking=False),
            "final_patch": tr.final_patch,
        })
    assert len(sft_records) == 1
    assert sft_records[0]["bug_id"] == "B-1"


def test_listing_surface(tmp_path: Path):
    _seed_minimal(tmp_path)
    assert list_experiments(tmp_path / "data") == ["exp"]
    assert list_bugs(tmp_path / "data", "exp") == ["B-1"]


def test_schema_types_are_exported():
    # Downstream writes type hints against these names:
    assert apr_agent.Trajectory is Trajectory
    assert apr_agent.Turn is Turn
    assert apr_agent.Event is Event
    assert apr_agent.BugSample is BugSample
    assert apr_agent.VerifyResult is VerifyResult
```

**Step 2: Run, verify pass**

Run: `uv run pytest tests/test_contract_downstream.py -v`
Expected: 4 passed.

**Step 3: Commit**

```bash
git add tests/test_contract_downstream.py
git commit -m "test: downstream contract test (summarizer + small-model flows)"
```

---

## Task 17: Final gate — ruff + full test run

**Step 1: Run ruff**

Run: `uv run ruff check .`
Expected: no errors. Fix any warnings that appear (imports, unused names).

**Step 2: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests from Task 2–16 pass. Should be ~33 tests.

**Step 3: Produce a coverage summary**

`pytest-cov` was added to `[project.optional-dependencies].dev` in Task 1, so no extra install needed.

Run:
```bash
uv run pytest --cov=apr_agent --cov-report=term-missing
```
Expected: coverage ≥ 80% on `apr_agent/*` (per global rule). If anything is under 80%, add targeted tests.

**Step 4: Commit any lint fixes**

```bash
git add -A
git commit -m "chore: lint cleanup for M1"
```

**Step 5: Tag M1**

```bash
git tag -a v0.1.0-m1 -m "M1 foundation: schema + writer + fake e2e complete"
```

---

## M1 Deliverables (what the next human / agent should see)

After finishing Task 17, the following must be true:

1. `uv run pytest` → all green, ≥ 80% coverage on `apr_agent/`
2. `uv run apr-agent --help` → shows `run-batch`
3. A downstream consumer can do:
   ```python
   import apr_agent
   for t in apr_agent.iter_trajectories("data", "exp", only_fixed=True):
       msgs = apr_agent.get_turns_as_messages(t)
   ```
   and it works.
4. `docs/plans/2026-04-24-apr-agent-design.md` + this plan are in git.
5. Schema is frozen enough to ship to the two downstream teammates — they can start writing code against it even though M2 (Defects4J) and M3 (Qwen) are pending.

---

## Out of scope (follow-up plan docs to write)

- **M2 plan**: real tools (`read_file`, `replace_block`, `run_tests`, `search_code`, `list_directory`, `get_failing_tests`) + Defects4J env layer + independent verify
- **M3 plan**: real Qwen client (OpenAI SDK against DashScope), thinking parsing, cost tracking, subprocess worker
- **M4 plan**: orchestrator (spawn subprocess, progress reporting, AIMD concurrency, force-rerun)
- **M5 plan**: docs/smoke scripts/handoff to downstream teammates
- **(Optional) DB migration plan** if scale > 500 bugs
- **(Optional) HTTP API plan** if remote consumption is required
