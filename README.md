# apr-agent

LLM agent for automated program repair on Defects4J. Records every fix attempt as a structured trajectory (per-turn LLM request/response, tool calls, regression labels, final patch, independent verification result) under a frozen pydantic schema.

**Current release: v0.4.1** — schema 1.1, 8 tools, parallel orchestrator. Trajectory datasets are distributed as tarballs (not committed to the repo) — see [Datasets](#datasets) below.

---

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [Public API reference](#public-api-reference)
  - [Reading trajectories](#reading-trajectories)
  - [Transforms](#transforms)
  - [Statistics](#statistics)
  - [Decomposition write-back](#decomposition-write-back)
  - [Schema types](#schema-types)
- [Datasets](#datasets)
- [Schema versioning](#schema-versioning)
- [Producing / sharing trajectories](#producing--sharing-trajectories)
- [Tool reference](#tool-reference)
- [Design](#design)
- [Development](#development)
- [Versions](#versions)

---

## Install

```bash
git clone https://github.com/QishengLu/nlp_project.git
cd nlp_project
uv venv --python 3.11 && source .venv/bin/activate
uv pip install -e .
```

Without the data:

```bash
uv pip install "git+https://github.com/QishengLu/nlp_project.git@v0.4.0"
```

Requires Python ≥ 3.11. Reading trajectories needs no other system dependency.

---

## Quick start

The repo ships **code only**. Trajectory datasets are distributed as tarballs
(see [Datasets](#datasets)). Drop one under `data/trajectories/` then iterate:

```bash
tar xzf math-distill-60.tar.gz       # extracts data/trajectories/math-distill-60/
```

```python
import apr_agent

# Read whatever experiment you've placed under data/trajectories/
for tr in apr_agent.iter_trajectories("data", "math-distill-60", only_fixed=True):
    msgs = apr_agent.get_turns_as_messages(tr, include_thinking=True)
    print(tr.bug_id, len(msgs), "messages,",
          len([t for t in tr.turns if t.regression_summary]), "regression-aware turns")
```

---

## Public API reference

Importable from the package root: `from apr_agent import ...`. Anything outside this surface (`apr_agent.agent.*`, `apr_agent.tools.*`, `apr_agent.defects4j.*`, `apr_agent.orchestrator.*`, `apr_agent.llm.*`) is implementation-internal and may change between minor versions.

### Reading trajectories

#### `load_trajectory(data_root, exp_id, bug_id) -> Trajectory`

Load a single trajectory from disk. Raises `FileNotFoundError` if the bug dir doesn't exist; raises `SchemaVersionError` if the on-disk `schema_version` major is incompatible with this library.

```python
tr = apr_agent.load_trajectory("data", "final", "Mockito-29")
```

#### `list_experiments(data_root) -> list[str]`

Sorted list of experiment ids under `<data_root>/trajectories/`.

#### `list_bugs(data_root, exp_id, status_filter=None) -> list[str]`

Sorted bug ids under an experiment. `status_filter={"fixed"}` for fixed only.

#### `iter_trajectories(data_root, exp_id, *, only_fixed=False, status_in=None, lazy_load_events=False) -> Iterator[Trajectory]`

Yields `Trajectory` objects. `only_fixed=True` is shorthand for `status_in={"fixed"}`. `lazy_load_events` is reserved for forward-compat (currently no-op).

### Transforms

#### `get_turns_as_messages(trajectory, *, include_thinking=False, include_system=True) -> list[dict]`

Convert a `Trajectory` to OpenAI chat-template messages, ready to drop into an SFT pipeline.

Output structure:
```
[{"role": "system",    "content": ...},                              # turn 0's system prompt (if include_system)
 {"role": "user",      "content": ...},                              # turn 0's user prompt
 {"role": "assistant", "content": ..., "tool_calls": [...]},         # per turn, with tool_calls if any
 {"role": "tool",      "tool_call_id": ..., "content": ...},          # one per tool_call
 ...]
```

If `include_thinking=True`, the assistant's `content` is prefixed with `<think>{trajectory.turns[i].thinking}</think>\n` whenever the turn has reasoning content.

#### `get_events_stream(trajectory) -> list[Event]`

Returns the persisted event stream in order. Convenient for fine-grained timeline analysis (turn boundaries, individual tool_call_start/end timestamps).

#### `get_trajectory_for_summarization(trajectory, *, format="messages"|"narrative"|"events")`

Shape a trajectory for step-summarization prompts:
- `"messages"`: same as `get_turns_as_messages(trajectory, include_thinking=True)`
- `"narrative"`: single human-readable string with turn boundaries, tool calls, and outputs (truncated)
- `"events"`: same as `get_events_stream`

### Statistics

#### `get_experiment_summary(data_root, exp_id) -> ExperimentSummary`

Fast counts across all bugs in an experiment. Returns a dataclass:

```python
@dataclass
class ExperimentSummary:
    exp_id: str
    total: int                 # bugs with a meta.json (excludes .trash dirs)
    fixed: int
    failed: int
    running: int
    error: int
    timeout: int
    aborted: int
    fix_rate: float            # fixed / total, 0 if total==0
    bug_ids: list[str]
```

### Decomposition write-back

#### `write_decomposed_steps(data_root, exp_id, bug_id, steps) -> None`

Persist the step-summarizer's output alongside the trajectory at `<bug_dir>/decomposed_steps.json`. `steps` shape is downstream-defined; this library doesn't validate it. Raises `FileNotFoundError` if the bug dir doesn't exist.

#### `read_decomposed_steps(data_root, exp_id, bug_id) -> list[dict] | None`

Read the decomposed steps if present, else `None`.

### Schema types

All schema types use `pydantic.BaseModel` with `extra="ignore"` so old readers won't crash on newer (additive) trajectories within the same major version.

#### `Trajectory`

The complete record for one bug attempt.

| Field | Type | Meaning |
|---|---|---|
| `exp_id` | `str` | Experiment id (e.g. `"final"`) |
| `bug_id` | `str` | Bug id (e.g. `"Math-50"`) |
| `status` | `Literal["running","fixed","failed","aborted","timeout","error"]` | Final outcome (decided by independent verify, not the agent's `finish` call) |
| `bug_sample` | `BugSample` | Bug metadata captured at checkout |
| `turns` | `list[Turn]` | Every LLM round-trip in order |
| `events` | `list[Event]` | Per-turn flat event stream (turn_start/llm_response/tool_call_start/tool_call_end/turn_end) |
| `final_patch` | `str` | `git diff HEAD` of agent's edits (the answer) |
| `verify` | `VerifyResult \| None` | Independent fresh-checkout verification (None if patch was empty) |
| `tool_registry` | `list[dict]` | OpenAI function schemas the agent saw |
| `meta` | `dict` | Extra metadata: `schema_version`, `model_name`, `apr_agent_version`, `started_at`, `ended_at`, `duration_s`, `stop_reason`, `env_fingerprint`, etc. |

#### `BugSample`

Per-bug metadata captured at Defects4J checkout time.

| Field | Type | Meaning |
|---|---|---|
| `bug_id` | `str` | E.g. `"Math-12"` |
| `project` | `str` | E.g. `"Math"` |
| `bug_number` | `int` | E.g. `12` |
| `buggy_checkout_dir` | `str` | Absolute path of the agent's working directory (typically deleted after run) |
| `trigger_tests` | `list[str]` | Authoritative bug-triggering tests from `defects4j export -p tests.trigger`. The "spec" the fix must satisfy. |
| `currently_failing` | `list[str]` | Tests observed to fail at checkout time (subset of, but usually equal to, trigger_tests) |
| `trigger_test_output` | `str` | Pre-captured failure trace from running the first trigger test once before the agent starts. Embedded into the user prompt's `{trigger_test_output}` placeholder. |
| `defects4j_version` | `str` | E.g. `"2.0.1"` |
| `d4j_subset` | `str \| None` | E.g. `"1.2"` for the classic 6-project APR baseline, `"2.0"` for the 17-project modern slice |
| `loc_hints` | `dict \| None` | Reserved for future use (location hints) |

#### `Turn`

One LLM round-trip = one entry in `turns.jsonl`.

| Field | Type | Meaning |
|---|---|---|
| `turn_idx` | `int` | 0-indexed |
| `started_at` / `ended_at` | `float` | Unix timestamps |
| `request` | `dict` | The full body sent to the LLM (sensitive headers like `Authorization` are masked before persisting) |
| `response` | `dict` | `{"parsed": {"content", "stop_reason", "tool_calls"}, "raw": <full provider dump>}`. **`parsed` is the stable contract; `raw` shape varies by provider.** |
| `thinking` | `str \| None` | Extracted from `message.reasoning_content` (DashScope thinking models) or inline `<think>...</think>` |
| `usage` | `dict` | MUST contain `prompt_tokens` and `completion_tokens` (0 if unknown), plus optional `total_tokens` |
| `tool_calls` | `list[ToolCall]` | Tool calls the LLM emitted this turn (0, 1, or N) |
| `regression_summary` | `dict \| None` | **Schema 1.1+.** Auto-extracted from the last successful `run_tests` tool_call's `tool_meta`, if any. Lets you filter "agent saw regression and reacted" patterns without re-parsing each ToolCall. Shape: `{"currently_failing": [...], "newly_failing": [...], "still_failing": [...], "now_passing": [...]}`. |

#### `ToolCall`

| Field | Type | Meaning |
|---|---|---|
| `call_id` | `str` | Provider-assigned unique id |
| `tool_name` | `str` | One of `read_file`, `list_directory`, `search_code`, `replace_block`, `run_tests`, `get_failing_tests`, `get_current_diff`, `finish` |
| `tool_input` | `dict` | Parsed JSON args. Empty `{}` if the LLM emitted malformed JSON (with `tool_meta["error"]="malformed_tool_arguments"`). |
| `tool_output` | `str` | The text the LLM saw as the tool's response. **On error, prefixed with `"ERROR: <reason>"`** (was empty pre-v0.4.0). |
| `tool_meta` | `dict` | Structured metadata: `error`, `applied`, `matches`, `path`, `failing_count`, `currently_failing`, `newly_failing`, `still_failing`, `now_passing`, `runtime_s`, `exit_code`, `chars`, `truncated`, etc. — varies by tool. |
| `started_at` / `ended_at` | `float` | Per-tool wall-clock timing |
| `is_error` | `bool` | True if the tool raised, returned an error, timed out, or matched 0/multiple times for replace_block |

#### `Event`

Flat per-event timeline persisted to `events.jsonl`.

| Field | Type | Meaning |
|---|---|---|
| `event_id` | `int` | Monotonic 0-indexed |
| `turn_idx` | `int` | Which turn this event belongs to |
| `at` | `float` | Unix timestamp |
| `kind` | `Literal["turn_start", "llm_response", "thinking", "text_block", "tool_call_start", "tool_call_end", "error", "turn_end", "verify_start", "verify_end"]` | |
| `payload` | `dict` | Event-specific (e.g. `tool_call_start` carries `{call_id, tool_name, tool_input}`) |

#### `VerifyResult`

Independent verification result on a fresh `defects4j checkout`.

| Field | Type | Meaning |
|---|---|---|
| `all_passing` | `bool` | True iff zero tests fail in the suite after applying the patch |
| `previously_failing_now_passing` | `list[str]` | Trigger tests fixed by the patch |
| `newly_failing` | `list[str]` | Tests broken by the patch (regressions) |
| `patch_applied` | `bool` | False if `git apply` and `patch -p1` both rejected |
| `test_exit_code` | `int` | `defects4j test` exit code |
| `runtime_s` | `float` | Wall-clock for the test run |
| `raw_output` | `str` | Tail of stdout/stderr (~200 lines) |

#### `SchemaVersionError`

Raised by `load_trajectory` when the on-disk `meta.schema_version` has a different MAJOR than this library's `SCHEMA_VERSION`. Subclass of `RuntimeError`.

---

## Datasets

This repo holds **code only**. Generated trajectory data is not committed —
`data/trajectories/` is gitignored except for its README. Datasets are
distributed as tarballs the producer uploads / sends out of band.

Available datasets (ask the producer for a download link):

| Tarball | Content | Size | Schema |
|---|---|---|---|
| `math-distill-60.tar.gz` | 60 verified-fixed Math trajectories (subset of 81 fixed from Math-1..91 attempts) | ~20 MB | 1.1 |
| `final-16.tar.gz` *(legacy)* | 16 trajectories, one per Defects4J project (Cli/Closure/Codec/Collections/Compress/Csv/Gson/JacksonCore/JacksonDatabind/JacksonXml/Jsoup/JxPath/Lang/Math/Mockito/Time) | ~12 MB | 1.1 |

All trajectories have `meta.status == "fixed"`, `verify.all_passing == True`,
no `newly_failing` tests, and a non-empty `final_patch.diff`. Generation env
for both: `qwen3.5-plus` via DashScope, `max_turns=60`, `temperature=0.2`,
`enable_thinking=true`.

### How to use a dataset

```bash
# In the project root after cloning the repo:
tar xzf math-distill-60.tar.gz                # → data/trajectories/math-distill-60/
```

```python
import apr_agent
for tr in apr_agent.iter_trajectories("data", "math-distill-60", only_fixed=True):
    msgs = apr_agent.get_turns_as_messages(tr, include_thinking=True)
    # msgs is OpenAI chat-template, ready for SFT
```

### Per-bug on-disk layout

```
data/trajectories/<exp_id>/<bug_id>/
├── meta.json              status, schema_version="1.1", env_fingerprint, timing
├── bug_sample.json        BugSample
├── tool_registry.json     OpenAI function schemas the agent saw (8 tools)
├── turns.jsonl            one Turn per line (request/response/tool_calls/usage/regression_summary)
├── events.jsonl           one Event per line
├── final_patch.diff       agent's edits as `git diff HEAD`
└── verify_result.json     independent fresh-checkout verification
```

---

## Schema versioning

`meta.schema_version` is the contract between producer and consumers.

- **MAJOR bump** = breaking change (rename, remove, or re-mean a field). `load_trajectory` raises `SchemaVersionError` rather than silently mis-load.
- **MINOR bump** = additive only. Old readers still parse the trajectory; they just don't see the new fields.

| Version | Date | Changes |
|---|---|---|
| **1.1** | current | Added `Turn.regression_summary` (optional). RunTestsTool emits structured `newly_failing`/`still_failing`/`now_passing`/`currently_failing` in `tool_meta`. New `get_current_diff` tool registered. |
| 1.0 | initial | M1 baseline: full schema as documented in [docs/plans/2026-04-24-apr-agent-design.md §5](docs/plans/2026-04-24-apr-agent-design.md). |

---

## Producing / sharing trajectories

Requires Java 8, Defects4J, and a DashScope API key. All vendored under `vendor/`; bootstrap is a single command.

### Where data lives

Trajectories the agent produces land under `data/trajectories/<exp_id>/<bug_id>/`.
**The whole `data/trajectories/` directory is gitignored** (except its README) —
generated data is too large and too transient for git. To share a dataset
with downstream consumers, tarball it:

```bash
tar czf my-exp.tar.gz data/trajectories/my-exp/
# upload / send out of band; recipient extracts in their project root.
```

The recipient just runs `tar xzf my-exp.tar.gz` and the layout is correct.
There is no extra import or registration step.

### One-time setup

```bash
git clone https://github.com/QishengLu/nlp_project.git
cd nlp_project
bash scripts/bootstrap_vendor.sh        # ~5 min, ~1.8GB → vendor/{jdk8,defects4j,perl5}
uv venv --python 3.11
source scripts/activate_env.sh          # JAVA_HOME, defects4j on PATH, .venv, TZ=America/Los_Angeles
uv pip install -e ".[dev]"
echo "DASHSCOPE_API_KEY=sk-..." > .env && chmod 600 .env
```

### Running

```bash
source scripts/activate_env.sh
set -a; source .env; set +a

apr-agent run-batch \
    --config configs/bugs.yaml \
    --exp-id my-exp \
    --data-root data \
    --scratch-root scratch \
    --bugs Math-70,Lang-21,Mockito-29 \
    --concurrency 5 \
    --overall-timeout-s 1800

apr-agent summary --exp-id my-exp
```

### CLI flags

| Flag | Default | Meaning |
|---|---|---|
| `--config` | required | Path to YAML config (e.g. `configs/bugs.yaml`) |
| `--exp-id` | required | Experiment id; trajectories land under `<data_root>/trajectories/<exp_id>/` |
| `--data-root` | `data` | Where trajectories are written |
| `--scratch-root` | `scratch` | Where Defects4J checkouts live (deleted after each bug) |
| `--bugs` | (use yaml `bugs:`) | Comma-separated bug-id override |
| `--skip-verify` | False | Skip the independent verify step (faster but `status` becomes meaningless) |
| `--overall-timeout-s` | 1800 | Per-worker subprocess wall-clock limit |
| `--concurrency`, `-j` | 1 | Parallel workers (each ~1-2GB RAM for the JVM) |

### Project caveats

- **Chart**: requires `svn` (Defects4J uses an SVN mirror); `bootstrap_vendor.sh` does not install it. All other 16 projects work.
- **Closure**: compile is slow (~5 min/bug); raise `--overall-timeout-s` to ≥1800 if Closure is in your batch.

---

## Tool reference

Eight tools live in the per-bug agent registry. The agent sees their OpenAI function-call schemas.

| Tool | Args | Output (success) | Output (error) |
|---|---|---|---|
| `read_file` | `path`, `start_line=1`, `end_line=-1` | Numbered lines: `   N\| <content>` (gutter `\| ` so indent is unambiguous) | `ERROR: file not found: ...` etc. |
| `list_directory` | `path=.`, `recursive=false`, `max_entries=200` | One entry per line; dirs end with `/`; ignores `.git`/`build`/`target` | `ERROR: not a directory: ...` etc. |
| `search_code` | `pattern`, `path=.`, `is_regex=false`, `max_results=50` | JSON `[{file,line,content}, ...]`; ripgrep if available, else pure-Python fallback | `ERROR: empty pattern` |
| `replace_block` | `path`, `old_code`, `new_code` | `applied 1 replacement in <path>` + mini-diff (3 lines context) | `ERROR: old_code not found ...` / `... matches N places ...` / `... protected trigger test ...` |
| `run_tests` | `test_filter=None`, `timeout_s=300` | `failing: N` + **regression block** (`newly_failing`/`still_failing`/`now_passing` against the bug's baseline trigger tests) + tail | `ERROR running tests: ...` |
| `get_failing_tests` | (none) | Newline-separated test ids | `ERROR: ...` |
| `get_current_diff` | (none) | Cumulative `git diff HEAD` (capped at 30K chars) | `(no edits made yet — agent has not modified any file)` if untouched |
| `finish` | `rationale` | empty (terminates the loop) | n/a |

`replace_block` cannot edit any path returned by `defects4j export -p tests.trigger` — that's a hard deny-list seeded into the tool at worker startup so the agent can't game its own evaluation.

---

## Design

| Document | Scope |
|---|---|
| [docs/plans/2026-04-24-apr-agent-design.md](docs/plans/2026-04-24-apr-agent-design.md) | Architecture, schema, tool list, verify, anti-cheat |
| [docs/plans/2026-04-24-apr-agent-m1-foundation.md](docs/plans/2026-04-24-apr-agent-m1-foundation.md) | M1 implementation plan |
| [tests/test_contract_downstream.py](tests/test_contract_downstream.py) | Executable contract — every public name above is exercised here |

---

## Development

```bash
uv pip install -e ".[dev]"
uv run pytest                              # full suite, ~80s (includes Defects4J integration)
uv run pytest -m "not defects4j"           # skip D4J-dependent tests, ~3s
uv run pytest --cov=apr_agent              # coverage
uv run ruff check .
```

109 tests, ~95% coverage on pure-logic paths.

---

## Versions

- `v0.1.0-m1` — schema 1.0, JSONL writer, FakeLLM end-to-end
- `v0.3.0-m3` — real tools, Defects4J env layer, Qwen client, subprocess worker, sequential orchestrator
- `v0.3.1-trajectories` — above + 13 fixed trajectories (single-thread baseline; data was committed; deprecated)
- `v0.4.0` — schema 1.1 (`regression_summary`), 8 tools (added `get_current_diff`), parallel orchestrator (`--concurrency`), tool error messages in `tool_output`, gutter separator fix
- **`v0.4.1` (current)** — `AgentLoop` now sanitizes echoed `tool_calls.arguments` before sending the next-turn request (fixes a DashScope 400 when the LLM emits malformed JSON args). `data/trajectories/` is now fully gitignored — datasets ship as tarballs out of band.

Roadmap: M5 (handoff/docs polish), M6+ (scale to 100+ bugs, migrate JSONL → SQLite — see [design doc §15](docs/plans/2026-04-24-apr-agent-design.md)).
