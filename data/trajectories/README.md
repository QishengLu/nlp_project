# Shipped trajectories

16 successfully-fixed Defects4J bugs, one per project (every Defects4J 2.x project except Chart, which requires SVN). Every trajectory in this directory has `meta.json:status="fixed"` AND `verify_result.json:all_passing=true` AND no newly-failing tests — i.e. an independent fresh-checkout verifier confirmed the patch.

| Project | Bug | Turns |
|---|---|---|
| Cli | Cli-11 | 14 |
| Closure | Closure-62 | 12 |
| Codec | Codec-2 | 14 |
| Collections | Collections-26 | 16 |
| Compress | Compress-19 | 10 |
| Csv | Csv-11 | 9 |
| Gson | Gson-15 | 11 |
| JacksonCore | JacksonCore-5 | 6 |
| JacksonDatabind | JacksonDatabind-1 | 20 |
| JacksonXml | JacksonXml-5 | 16 |
| Jsoup | Jsoup-26 | 15 |
| JxPath | JxPath-22 | 23 |
| Lang | Lang-21 | 8 |
| Math | Math-70 | 9 |
| Mockito | Mockito-29 | 13 |
| Time | Time-7 | 34 |

**Generation env**: model=`qwen3.5-plus` (DashScope OpenAI-compatible endpoint), `max_turns=60`, `temperature=0.2`, `enable_thinking=true`. 8-tool registry (`read_file`, `list_directory`, `search_code`, `replace_block` with trigger-test deny-list, `run_tests` with regression labels, `get_failing_tests`, `get_current_diff`, `finish`). `apr_agent` 0.4.0, `schema_version=1.1`. Total agent compute 31.8 min; wall clock ~10 min with concurrency=5. See `meta.json/env_fingerprint` per trajectory for defects4j commit + Java version + host.

## Per-trajectory layout

    final/<bug_id>/
    ├── meta.json              status, schema_version="1.1", env_fingerprint, timing
    ├── bug_sample.json        BugSample (trigger_tests, defects4j_version, ...)
    ├── tool_registry.json     OpenAI function schemas the agent saw (8 tools)
    ├── turns.jsonl            one Turn per line (request/response/tool_calls/usage/regression_summary)
    ├── events.jsonl           one Event per line
    ├── final_patch.diff       agent's edits as `git diff HEAD`
    └── verify_result.json     fresh-checkout independent verification

## Reading

    import apr_agent

    for tr in apr_agent.iter_trajectories("data", "final", only_fixed=True):
        # SFT chat-template messages, with thinking included as <think> blocks
        msgs = apr_agent.get_turns_as_messages(tr, include_thinking=True)

        # Independent verify confirms the fix
        assert tr.verify is not None and tr.verify.all_passing

        # Schema 1.1: structured regression info per turn (None when no run_tests this turn)
        regression_aware_turns = [t for t in tr.turns if t.regression_summary]

See [tests/test_contract_downstream.py](../../tests/test_contract_downstream.py) for the contract surface downstream is allowed to depend on.

The full schema documentation lives in the project [README](../../README.md#schema-types).
