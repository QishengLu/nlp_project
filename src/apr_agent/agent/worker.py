"""Per-bug subprocess worker. Reads a JSON payload on stdin, runs the agent
loop end-to-end, records the trajectory, runs independent verify.

The worker is what the orchestrator spawns for each bug. It never coordinates
with other workers — all scheduling lives in the orchestrator. Worker exit
code:
    0 - trajectory completed and persisted (regardless of fixed/failed)
    2 - malformed payload
    3 - uncaught error before trajectory was even started
The trajectory's `meta.status` is the semantic outcome; exit code just gates
"can the orchestrator read meta.json from disk".
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from apr_agent.agent.loop import AgentConfig, AgentLoop
from apr_agent.defects4j.checkout import (
    CheckedOut,
    checkout_bug,
    diff_from_baseline,
    git_init_baseline,
    teardown,
)
from apr_agent.defects4j.info import trigger_test_files
from apr_agent.defects4j.verify import verify_patch
from apr_agent.env_fingerprint import env_fingerprint
from apr_agent.llm.client import LLMClient
from apr_agent.llm.fake import FakeLLMClient, ScriptedResponse
from apr_agent.llm.qwen import QwenClient, QwenConfig
from apr_agent.schema import BugSample
from apr_agent.tools.finish import FinishTool
from apr_agent.tools.get_failing import GetFailingTestsTool
from apr_agent.tools.list_directory import ListDirectoryTool
from apr_agent.tools.read_file import ReadFileTool
from apr_agent.tools.registry import ToolRegistry
from apr_agent.tools.replace_block import ReplaceBlockTool
from apr_agent.tools.run_tests import RunTestsTool
from apr_agent.tools.search_code import SearchCodeTool
from apr_agent.trajectory.recorder import TrajectoryRecorder


@dataclass
class WorkerPayload:
    bug_id: str
    exp_id: str
    data_root: str
    scratch_root: str
    model: dict                          # QwenConfig fields, or {"type":"fake", "script":[...]}
    agent: dict                          # AgentConfig fields (max_turns, prompts, ...)
    dataset: dict                        # defects4j_version, d4j_subset, ...
    verify: bool = True                  # run verify after agent loop


def main() -> int:
    # TZ is locked to America/Los_Angeles for every defects4j invocation below.
    # Defects4J tests are timezone-sensitive; if the parent has a different TZ,
    # enforce here at process entry as a safety net in case we spawn tools
    # outside the defects4j runner.
    os.environ["TZ"] = "America/Los_Angeles"
    time.tzset()

    try:
        raw = sys.stdin.read()
        payload_dict = json.loads(raw)
        payload = WorkerPayload(**payload_dict)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"worker: malformed payload: {e}", file=sys.stderr)
        return 2

    try:
        run_worker(payload)
        return 0
    except Exception as e:
        traceback.print_exc()
        print(f"worker: uncaught error: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


def run_worker(payload: WorkerPayload) -> None:
    started_at = time.time()
    scratch_root = Path(payload.scratch_root)
    data_root = Path(payload.data_root)

    # 1. Defects4J checkout — needs real defects4j on PATH.
    checkout = checkout_bug(payload.bug_id, scratch_root=scratch_root)
    try:
        git_init_baseline(checkout.work_dir)

        # 2. Build BugSample from the metadata we just learned.
        bug_sample = _bug_sample_from_checkout(checkout, payload.dataset)

        # 3. Tools bound to the checkout's work_dir.
        registry = _build_registry(checkout)

        # 4. Recorder with fingerprint.
        model_id = payload.model.get("name", payload.model.get("type", "unknown"))
        meta_extras = {
            "model_name": model_id,
            "apr_agent_version": _version(),
            "started_at": started_at,
            "env_fingerprint": env_fingerprint(
                model_id=model_id,
                defects4j_version=payload.dataset.get("defects4j_version"),
                d4j_subset=payload.dataset.get("d4j_subset"),
            ),
        }
        recorder = TrajectoryRecorder.start(
            data_root=data_root,
            exp_id=payload.exp_id,
            bug_sample=bug_sample,
            tool_registry=registry.openai_schemas(),
            meta_extras=meta_extras,
        )

        # 5. Build LLM client + agent loop.
        llm = _build_llm(payload.model)
        cfg = _build_config(payload.agent)
        loop = AgentLoop(llm=llm, tools=registry, config=cfg)

        stop_reason, turns = loop.run(bug_sample)
        for turn in turns:
            recorder.record_turn(turn)

        # 6. Persist the agent's final diff.
        final_patch = diff_from_baseline(checkout.work_dir)
        recorder.write_patch(final_patch)

        # 7. Independent verify on a fresh checkout.
        verify_status = "failed"
        if payload.verify and final_patch.strip():
            vresult = verify_patch(
                payload.bug_id, final_patch,
                scratch_root=scratch_root / "verify",
            )
            recorder.write_verify(vresult)
            verify_status = "fixed" if vresult.all_passing else "failed"
        elif not final_patch.strip():
            verify_status = "failed"   # empty diff, nothing to verify

        ended_at = time.time()
        status = verify_status if stop_reason == "finish" else {
            "max_turns": "failed",
            "finish": verify_status,
        }.get(stop_reason, "failed")

        recorder.finalize(status=status, extra={
            "stop_reason": stop_reason,
            "ended_at": ended_at,
            "duration_s": round(ended_at - started_at, 2),
        })
    finally:
        teardown(checkout)


# --- builders ---

def _build_registry(checkout: CheckedOut) -> ToolRegistry:
    wd = checkout.work_dir
    protected = trigger_test_files(checkout.metadata)
    reg = ToolRegistry()
    reg.register(ReadFileTool(wd))
    reg.register(ListDirectoryTool(wd))
    reg.register(SearchCodeTool(wd))
    reg.register(ReplaceBlockTool(wd, protected_paths=protected))
    reg.register(RunTestsTool(wd))
    reg.register(GetFailingTestsTool(wd))
    reg.register(FinishTool())
    return reg


def _build_llm(model_cfg: dict) -> LLMClient:
    kind = model_cfg.get("type", "qwen")
    if kind == "fake":
        scripts = [
            ScriptedResponse(
                content=r.get("content", ""),
                tool_calls=r.get("tool_calls", []),
                stop_reason=r.get("stop_reason", "stop"),
                thinking=r.get("thinking"),
            )
            for r in model_cfg.get("script", [])
        ]
        return FakeLLMClient(scripts)
    qc = QwenConfig(
        model=model_cfg.get("name", "qwen3-coder-30b-a3b-instruct"),
        base_url=model_cfg.get("base_url", QwenConfig.base_url),
        enable_thinking=bool(model_cfg.get("enable_thinking", True)),
        extra_body=model_cfg.get("extra_body"),
    )
    return QwenClient(qc)


def _build_config(agent_cfg: dict) -> AgentConfig:
    return AgentConfig(
        max_turns=int(agent_cfg.get("max_turns", 30)),
        system_prompt=agent_cfg.get("system_prompt", "You are an APR agent."),
        user_prompt_template=agent_cfg.get(
            "user_prompt_template",
            "Fix {bug_id}. Trigger tests: {trigger_tests}\n{trigger_test_output}",
        ),
        temperature=float(agent_cfg.get("temperature", 0.2)),
        max_tokens=int(agent_cfg.get("max_tokens", 4096)),
    )


def _bug_sample_from_checkout(checkout: CheckedOut, dataset: dict) -> BugSample:
    return BugSample(
        bug_id=checkout.bug_id,
        project=checkout.project,
        bug_number=checkout.bug_number,
        buggy_checkout_dir=str(checkout.work_dir),
        trigger_tests=list(checkout.metadata.trigger_tests),
        currently_failing=list(checkout.metadata.trigger_tests),  # before agent edits
        trigger_test_output="",  # TODO(M4): run one test to capture the failure trace
        defects4j_version=dataset.get("defects4j_version", "2.0.1"),
        d4j_subset=dataset.get("d4j_subset"),
    )


def _version() -> str:
    try:
        from apr_agent import __version__
        return __version__
    except ImportError:
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())
