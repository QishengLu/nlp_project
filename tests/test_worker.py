"""Worker-level tests. Defects4j is mocked so the worker can be exercised
end-to-end without a real Defects4J install."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from apr_agent.agent import worker as worker_mod
from apr_agent.api import load_trajectory
from apr_agent.defects4j.checkout import CheckedOut
from apr_agent.defects4j.info import BugMetadata
from apr_agent.schema import VerifyResult


def _make_fake_checkout(scratch_root: Path, bug_id: str) -> CheckedOut:
    """Produce a plausible work_dir with a buggy file + a trigger test file."""
    import uuid
    work = scratch_root / f"{bug_id}-{uuid.uuid4().hex[:6]}"
    (work / "src/main/java").mkdir(parents=True)
    (work / "src/test/java").mkdir(parents=True)
    (work / "src/main/java/Foo.java").write_text(
        "public class Foo { public int add(int a,int b){ return a - b; } }\n"
    )
    (work / "src/test/java/FooTest.java").write_text(
        "public class FooTest { /* trigger */ }\n"
    )
    meta = BugMetadata(
        trigger_tests=["FooTest::bar"],
        relevant_tests=["FooTest::bar"],
        modified_classes=["Foo"],
        source_dir="src/main/java",
        test_dir="src/test/java",
        dir_src_classes="src/main/java",
        dir_src_tests="src/test/java",
    )
    return CheckedOut(work_dir=work, bug_id=bug_id,
                      project=bug_id.split("-")[0], bug_number=int(bug_id.split("-")[1]),
                      metadata=meta)


@pytest.fixture()
def patched_worker(monkeypatch, tmp_path: Path):
    """Stub out defects4j checkout/verify/git so worker can run without D4J."""
    fake = _make_fake_checkout(tmp_path / "scratch", "Math-12")

    def fake_checkout(bug_id, *, scratch_root, **_):
        return fake

    def noop_git_init(work_dir):
        # Real git_init_baseline exists and works; we can actually use it, but
        # tests shouldn't need network/git identity for that. Just stub.
        subprocess.run(["git", "init", "-q"], cwd=work_dir, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "add", "-A"], cwd=work_dir, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "base"], cwd=work_dir, check=True)

    def fake_diff(work_dir):
        return "--- a/Foo.java\n+++ b/Foo.java\n@@ -1 +1 @@\n-a - b\n+a + b\n"

    def fake_verify(bug_id, patch, *, scratch_root, **_):
        return VerifyResult(
            all_passing=True,
            previously_failing_now_passing=["FooTest::bar"],
            newly_failing=[],
            patch_applied=True,
            test_exit_code=0,
            runtime_s=1.0,
            raw_output="ok",
        )

    def fake_teardown(_):
        pass

    monkeypatch.setattr(worker_mod, "checkout_bug", fake_checkout)
    monkeypatch.setattr(worker_mod, "git_init_baseline", noop_git_init)
    monkeypatch.setattr(worker_mod, "diff_from_baseline", fake_diff)
    monkeypatch.setattr(worker_mod, "verify_patch", fake_verify)
    monkeypatch.setattr(worker_mod, "teardown", fake_teardown)
    return fake


def test_worker_happy_path_with_fake_llm(patched_worker, tmp_path: Path):
    payload = worker_mod.WorkerPayload(
        bug_id="Math-12",
        exp_id="exp-worker",
        data_root=str(tmp_path / "data"),
        scratch_root=str(tmp_path / "scratch"),
        model={
            "type": "fake",
            "script": [
                {"content": "I'll finish.",
                 "tool_calls": [{"id": "c1", "name": "finish",
                                 "arguments": {"rationale": "fix"}}]},
            ],
        },
        agent={"max_turns": 5, "system_prompt": "s",
               "user_prompt_template": "Fix {bug_id}"},
        dataset={"defects4j_version": "2.0.1", "d4j_subset": "2.0"},
        verify=True,
    )
    worker_mod.run_worker(payload)

    tr = load_trajectory(tmp_path / "data", "exp-worker", "Math-12")
    assert tr.status == "fixed"
    assert tr.verify is not None and tr.verify.all_passing is True
    assert tr.turns[0].tool_calls[0].tool_name == "finish"
    assert tr.meta["env_fingerprint"]["model_id"] == "fake"
    assert tr.meta["stop_reason"] == "finish"
    assert tr.bug_sample.trigger_tests == ["FooTest::bar"]


def test_worker_records_failed_when_patch_empty(monkeypatch, tmp_path: Path, patched_worker):
    monkeypatch.setattr(worker_mod, "diff_from_baseline", lambda w: "")
    payload = worker_mod.WorkerPayload(
        bug_id="Math-12",
        exp_id="exp-empty",
        data_root=str(tmp_path / "data"),
        scratch_root=str(tmp_path / "scratch"),
        model={"type": "fake",
               "script": [{"content": "done",
                           "tool_calls": [{"id": "c1", "name": "finish",
                                           "arguments": {"rationale": "none"}}]}]},
        agent={"max_turns": 3, "system_prompt": "s",
               "user_prompt_template": "Fix {bug_id}"},
        dataset={"defects4j_version": "2.0.1"},
        verify=True,
    )
    worker_mod.run_worker(payload)
    tr = load_trajectory(tmp_path / "data", "exp-empty", "Math-12")
    assert tr.status == "failed"
    assert tr.final_patch == ""


def test_worker_subprocess_entry_rejects_bad_json(tmp_path: Path):
    """The CLI-level entry: malformed stdin → exit code 2."""
    r = subprocess.run(
        [sys.executable, "-m", "apr_agent.agent.worker"],
        input="not json", text=True, capture_output=True,
    )
    assert r.returncode == 2
    assert "malformed payload" in r.stderr


# Helper used by the subprocess end-to-end test. Monkeypatches the worker
# module's defects4j-dependent names at import time.
_WORKER_STUB_SRC = """
import os, sys, subprocess, uuid
from pathlib import Path
from apr_agent.agent import worker as w
from apr_agent.defects4j.checkout import CheckedOut
from apr_agent.defects4j.info import BugMetadata
from apr_agent.schema import VerifyResult


def _mk(scratch_root, bug_id):
    work = Path(scratch_root) / f"{bug_id}-{uuid.uuid4().hex[:6]}"
    (work / "src").mkdir(parents=True)
    (work / "src/Foo.java").write_text("x\\n")
    meta = BugMetadata(
        trigger_tests=["FooTest::bar"], relevant_tests=["FooTest::bar"],
        modified_classes=["Foo"], source_dir="src", test_dir="src",
        dir_src_classes="src", dir_src_tests="src",
    )
    proj, num = bug_id.split("-")
    return CheckedOut(work_dir=work, bug_id=bug_id, project=proj,
                      bug_number=int(num), metadata=meta)


def patch():
    w.checkout_bug = lambda bug_id, *, scratch_root, **kw: _mk(scratch_root, bug_id)
    def git_init(wd):
        subprocess.run(["git", "init", "-q"], cwd=wd, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "add", "-A"], cwd=wd, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "b"], cwd=wd, check=True)
    w.git_init_baseline = git_init
    w.diff_from_baseline = lambda wd: "diff --git a/x b/x\\n--- a/x\\n+++ b/x\\n@@\\n-x\\n+y\\n"
    w.verify_patch = lambda bug_id, patch, *, scratch_root, **kw: VerifyResult(
        all_passing=True, previously_failing_now_passing=["FooTest::bar"],
        newly_failing=[], patch_applied=True, test_exit_code=0, runtime_s=0.1,
        raw_output="ok")
    w.teardown = lambda _: None


patch()
sys.exit(w.main())
"""


def test_worker_subprocess_entry_executes_payload_via_stub(tmp_path: Path):
    """Run the worker stub directly (cleanest way to exercise real __main__ flow)."""
    payload = {
        "bug_id": "Math-12",
        "exp_id": "exp-stub",
        "data_root": str(tmp_path / "data"),
        "scratch_root": str(tmp_path / "scratch"),
        "model": {"type": "fake",
                  "script": [{"content": "done",
                              "tool_calls": [{"id": "c1", "name": "finish",
                                              "arguments": {"rationale": "ok"}}]}]},
        "agent": {"max_turns": 3, "system_prompt": "s",
                  "user_prompt_template": "Fix {bug_id}"},
        "dataset": {"defects4j_version": "2.0.1"},
        "verify": True,
    }

    stub = tmp_path / "run_stub.py"
    stub.write_text(_WORKER_STUB_SRC)
    r = subprocess.run(
        [sys.executable, str(stub)],
        input=json.dumps(payload), text=True, capture_output=True,
    )
    assert r.returncode == 0, f"stderr:\n{r.stderr}"
    tr = load_trajectory(tmp_path / "data", "exp-stub", "Math-12")
    assert tr.status == "fixed"
