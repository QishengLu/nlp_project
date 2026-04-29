# Trajectory data

This directory is **gitignored** (apart from this README). Trajectory datasets
are shipped as tarballs out of band, not committed to the repo.

To use a dataset, extract its tarball in the project root — the layout
matches what `apr_agent.iter_trajectories` and friends expect:

```bash
tar xzf math-distill-60.tar.gz       # creates data/trajectories/math-distill-60/
```

```python
import apr_agent
for tr in apr_agent.iter_trajectories("data", "math-distill-60", only_fixed=True):
    msgs = apr_agent.get_turns_as_messages(tr, include_thinking=True)
    assert tr.verify is not None and tr.verify.all_passing
```

## Per-bug layout

```
<exp_id>/<bug_id>/
├── meta.json              status, schema_version, env_fingerprint, timing
├── bug_sample.json        BugSample (trigger_tests, defects4j_version, ...)
├── tool_registry.json     OpenAI function schemas the agent saw
├── turns.jsonl            one Turn per line
├── events.jsonl           one Event per line
├── final_patch.diff       agent's edits as `git diff HEAD`
└── verify_result.json     fresh-checkout independent verification
```

Schema field documentation lives in the project [README](../../README.md#schema-types)
and the design doc at [docs/plans/2026-04-24-apr-agent-design.md §5](../../docs/plans/2026-04-24-apr-agent-design.md).

The contract surface downstream is allowed to depend on is exercised in
[tests/test_contract_downstream.py](../../tests/test_contract_downstream.py).
