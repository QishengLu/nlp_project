# apr-agent

LLM agent for automated program repair on Defects4J. Records every step of every fix attempt as a structured trajectory (per-turn LLM request/response, tool calls, final patch, independent verification result) under a frozen pydantic schema.

Current release: **v0.3.1**. 13 verified fixed trajectories shipped under `data/trajectories/`, covering 9 Defects4J projects.

## Install

```bash
git clone https://github.com/QishengLu/nlp_project.git
cd nlp_project
uv venv --python 3.11 && source .venv/bin/activate
uv pip install -e .
```

Without the data:

```bash
uv pip install "git+https://github.com/QishengLu/nlp_project.git@v0.3.1-trajectories"
```

Requires Python ≥ 3.11. Reading trajectories needs no other system dependency.

## Usage

```python
import apr_agent

apr_agent.list_experiments("data")                        # ["batch-1", "batch-2", "smoke-4"]
apr_agent.list_bugs("data", "batch-2")                    # ["Cli-11", "Codec-2", ...]

tr = apr_agent.load_trajectory("data", "batch-2", "Mockito-29")
tr.status                                                 # "fixed"
tr.verify.all_passing                                     # True
tr.bug_sample.trigger_tests
len(tr.turns)

for tr in apr_agent.iter_trajectories("data", "batch-2", only_fixed=True):
    msgs = apr_agent.get_turns_as_messages(tr, include_thinking=True)
    # OpenAI chat-template; ready for SFT.

apr_agent.write_decomposed_steps("data", "batch-2", "Mockito-29", [
    {"step_id": 1, "kind": "locate", "summary": "..."},
])
```

### Public API

Importable from the package root. Anything outside this list (`apr_agent.agent.*`, `apr_agent.tools.*`, `apr_agent.defects4j.*`, …) is implementation-internal.

| Category | Names |
|---|---|
| Schema | `Trajectory`, `Turn`, `Event`, `ToolCall`, `BugSample`, `VerifyResult`, `ExperimentSummary`, `SchemaVersionError` |
| Read | `load_trajectory`, `iter_trajectories`, `list_bugs`, `list_experiments` |
| Transform | `get_turns_as_messages`, `get_events_stream`, `get_trajectory_for_summarization` |
| Stats | `get_experiment_summary` |
| Decomposition write-back | `write_decomposed_steps`, `read_decomposed_steps` |

[tests/test_contract_downstream.py](tests/test_contract_downstream.py) is the executable contract — every name above is exercised there.

## Dataset

13 fixed trajectories in [data/trajectories/](data/trajectories/), grouped by experiment id:

| Experiment | Bugs |
|---|---|
| `smoke-4` | Math-50 |
| `batch-1` | Math-3, Math-70, Lang-21, Lang-33, Lang-55 |
| `batch-2` | Mockito-29, Cli-11, Csv-11, Gson-15, JxPath-22, Jsoup-26, Codec-2 |

Per-bug layout:

```
<exp_id>/<bug_id>/
├── meta.json              status, schema_version, env_fingerprint, timing
├── bug_sample.json        BugSample (trigger_tests, defects4j_version, ...)
├── tool_registry.json     OpenAI function schemas the agent saw
├── turns.jsonl            one Turn per line
├── events.jsonl           one Event per line
├── final_patch.diff       agent's edits as `git diff HEAD`
└── verify_result.json     independent fresh-checkout verification
```

Generation env: `qwen3.5-plus` via DashScope, `max_turns=60`, `temperature=0.2`. Every trajectory shipped here has `meta.status=="fixed"` and `verify_result.all_passing==true` with no newly-failing tests. Fix rate over the run was 13/15 ≈ 87% (Chart project excluded — its Defects4J checkout requires SVN).

Schema version `1.0` is frozen. Major bumps will cause `load_trajectory` to raise `SchemaVersionError` rather than silently upgrade. Field definitions: [docs/plans/2026-04-24-apr-agent-design.md §5](docs/plans/2026-04-24-apr-agent-design.md).

## Producing new trajectories

Requires Java 8, Defects4J, and a DashScope API key.

```bash
bash scripts/bootstrap_vendor.sh          # one-time, ~5 min, ~1.8GB → vendor/
source scripts/activate_env.sh            # JDK 8, defects4j, perl5, .venv, TZ
echo "DASHSCOPE_API_KEY=sk-..." > .env && chmod 600 .env

set -a; source .env; set +a
apr-agent run-batch \
    --config configs/bugs.yaml \
    --exp-id my-exp \
    --bugs Math-3,Lang-33,Mockito-29

apr-agent summary --exp-id my-exp
```

Project caveats:
- **Chart**: requires `svn` (Defects4J uses an SVN mirror); `bootstrap_vendor.sh` does not install it.
- **Closure**: compile is slow (~5 min/bug); raise `--overall-timeout-s` to ≥1500 if including Closure bugs.

## Design

| Document | Scope |
|---|---|
| [docs/plans/2026-04-24-apr-agent-design.md](docs/plans/2026-04-24-apr-agent-design.md) | Architecture, schema, tool list, verify, anti-cheat |
| [docs/plans/2026-04-24-apr-agent-m1-foundation.md](docs/plans/2026-04-24-apr-agent-m1-foundation.md) | M1 implementation plan (task-by-task) |
| [data/trajectories/README.md](data/trajectories/README.md) | Trajectory dataset manifest |

## Development

```bash
uv pip install -e ".[dev]"
uv run pytest                              # full suite, ~80s (includes Defects4J integration)
uv run pytest -m "not defects4j"           # skip D4J-dependent tests, ~3s
uv run pytest --cov=apr_agent              # coverage
uv run ruff check .
```

103 tests, 95% coverage on pure-logic paths.

## Versions

- `v0.1.0-m1` — schema + JSONL writer + Fake-LLM end-to-end
- `v0.3.0-m3` — real tools, Defects4J env layer, Qwen client, subprocess worker, orchestrator
- `v0.3.1-trajectories` — above plus 13 fixed trajectories

Roadmap: M4 (AIMD concurrency), M5 (handoff), M6+ (scale to 100+ bugs, migrate JSONL → SQLite — see [design doc §15](docs/plans/2026-04-24-apr-agent-design.md)).
