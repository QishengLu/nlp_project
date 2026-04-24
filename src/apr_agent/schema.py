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
