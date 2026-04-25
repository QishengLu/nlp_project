# Shipped trajectories

13 successfully-fixed Defects4J bugs across 9 projects. Every trajectory in
this directory has `meta.json:status="fixed"` AND
`verify_result.json:all_passing=true` AND no newly-failing tests — i.e. an
independent fresh-checkout verifier confirmed the patch.

| Project   | Bugs                                  |
|-----------|---------------------------------------|
| Math      | Math-3, Math-50, Math-70              |
| Lang      | Lang-21, Lang-33, Lang-55             |
| Mockito   | Mockito-29                            |
| Cli       | Cli-11                                |
| Csv       | Csv-11                                |
| Gson      | Gson-15                               |
| JxPath    | JxPath-22                             |
| Jsoup     | Jsoup-26                              |
| Codec     | Codec-2                               |

**Generation env**: model=`qwen3.5-plus` (DashScope, OpenAI-compatible
endpoint), `max_turns=60`, `temperature=0.2`, `enable_thinking=true`.
Tool registry: `read_file`, `list_directory`, `search_code`,
`replace_block` (with trigger-test deny-list), `run_tests`,
`get_failing_tests`, `finish`. `apr_agent` 0.1.0,
`schema_version=1.0`. See `meta.json/env_fingerprint` per trajectory for
defects4j commit + Java version + host.

## Per-trajectory layout

    <exp_id>/<bug_id>/
    ├── meta.json              status, schema_version, env_fingerprint, timing
    ├── bug_sample.json        BugSample (trigger_tests, defects4j_version, ...)
    ├── tool_registry.json     OpenAI function schemas the agent saw
    ├── turns.jsonl            one Turn per line (request/response/tool_calls/usage)
    ├── events.jsonl           one Event per line (turn_start/llm_response/tool_call_*/turn_end)
    ├── final_patch.diff       `git diff HEAD` of agent's edits
    └── verify_result.json     all_passing, previously_failing_now_passing, newly_failing

`raw/` subdirectories (subprocess stdout/stderr) are gitignored — they were
either empty or never populated in M3.

## Reading trajectories

    import apr_agent
    for tr in apr_agent.iter_trajectories("data", "batch-1", only_fixed=True):
        # SFT chat-template messages, with thinking included as <think> blocks
        msgs = apr_agent.get_turns_as_messages(tr, include_thinking=True)
        # Independent verify outcome
        assert tr.verify is not None and tr.verify.all_passing
        # Final unified diff (the actual fix)
        print(tr.bug_id, len(tr.final_patch.splitlines()), "diff lines")

See [tests/test_contract_downstream.py](../../tests/test_contract_downstream.py)
for the contract surface downstream is allowed to depend on.
