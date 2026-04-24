# APR Agent — Design Doc

**Date**: 2026-04-24
**Status**: Approved (brainstorming phase complete)
**Owner**: me (大模型 agent 侧)
**Downstream consumers**:
- 总结同学：用 LLM 对 trajectory 做 step 总结/拆分
- 小模型同学：拿拆分好的步骤做 SFT 蒸馏

## 1. Goal

造一个大模型 agent（Qwen3-Coder-30B），给它一组 tool，让它在 Defects4J 数据集上自主修 bug；**忠实、完整地记录每一次 agent 交互**，并把这些 trajectory 以稳定 schema 暴露给下游两位同学消费。

本包不做 step 拆分、不做小模型训练、不做失败归因——只做**原料产出 + 数据契约**。

### Non-goals

- 不做 step decomposition（下游同学负责）
- 不做 SFT / 训练流水线（下游同学负责）
- 不做分布式多机调度（学期规模单机足够）
- 不预先做 HTTP API（按需再加）

## 2. Settled decisions

| # | 决定 | 原因 |
|---|-----|-----|
| D1 | **Self-written tool-use loop**，不用现成 agent 框架 | 轨迹格式必须我们完全可控，framework 的状态机难导成干净 messages |
| D2 | **Turn + flat event 双表达** 存储 | 下游同学的 LLM 切分粒度未知，两种视角都留 |
| D3 | **Schema-first，先 JSONL + 后 DB 可迁**（semester project 规模） | 契约稳定，存储后端可换 |
| D4 | **大模型 = Qwen3-Coder-30B-A3B-Instruct via DashScope OpenAI-compatible endpoint** | 用户指定 |
| D5 | **小模型由下游同学自选**，不是本包关心的范围 | 分工约定 |
| D6 | **Subprocess-per-bug 执行 + JSONL 存储** | 进程级隔离，JVM 吃内存必须隔，未来并发直接复用 RolloutRunner 的 AIMD |
| D7 | **7 个窄 tool，不给通用 shell** | 对小模型学友好；防 agent 自毁 |
| D8 | **Verify 独立跑在 subprocess 外** | 防 agent 改测试作弊，verify 必须可重放 |
| D9 | **Agent 不能改测试文件** | tool 层硬校验 path |
| D10 | **HTTP 不做，先 Python lib** | YAGNI |

## 3. Architecture

```
┌──────────────────────────────────────────────────────────┐
│  orchestrator (apr_agent.orchestrator.controller)         │
│    - 读 bug list (configs/bugs.yaml)                      │
│    - 为每个 bug spawn 一个 agent_worker subprocess         │
│    - 收 stdout progress log；轨迹由 worker 直接写盘          │
│    - Verify 独立跑（不经 LLM）                              │
│    - AIMD 并发（后期启用）                                   │
└────────┬─────────────────────────────────────────────────┘
         │ spawn + stdin JSON payload
         ▼
┌──────────────────────────────────────────────────────────┐
│  agent_worker.py (per-bug subprocess)                     │
│    - defects4j checkout → scratch/<bug_id>-<uuid>/        │
│    - 初始化 Qwen client (openai SDK)                        │
│    - 启动 tool-use loop                                    │
│    - trajectory_recorder 实时追加 events.jsonl / turns.jsonl│
│    - finish(rationale) 时终止 loop                          │
└────────┬─────────────────────────────────────────────────┘
         ▼
┌────────────────────┬──────────────────┬──────────────────┐
│  tools/            │ trajectory/      │ defects4j/       │
│    read_file       │   recorder       │   checkout       │
│    list_directory  │   turn_model     │   runner         │
│    search_code     │   event_model    │   info           │
│    replace_block   │   writer_jsonl   │                  │
│    run_tests       │   (future: db)   │                  │
│    get_failing     │                  │                  │
│    finish          │                  │                  │
└────────────────────┴──────────────────┴──────────────────┘
                           │
                           ▼
                    data/trajectories/<exp_id>/<bug_id>/
                       meta.json / turns.jsonl / events.jsonl
                       final_patch.diff / verify_result.json
                       bug_sample.json / tool_registry.json
                       raw/ (subprocess stdout/stderr/defects4j_test.log)
```

## 4. Package layout (src-layout, pip-installable)

```
nlp_project/
├── pyproject.toml                  # hatchling backend, openai/pydantic/typer
├── README.md
├── .env.example                    # QWEN_API_KEY, QWEN_BASE_URL, DEFECTS4J_HOME, ...
├── src/
│   └── apr_agent/
│       ├── __init__.py             # re-export from api.py
│       ├── api.py                  # ★ 对外稳定接口
│       ├── schema.py               # ★ pydantic 数据契约
│       ├── agent/
│       │   ├── worker.py           # subprocess entry
│       │   ├── loop.py             # tool-use while-loop
│       │   └── prompts.py
│       ├── llm/
│       │   └── client.py           # openai SDK 指向 DashScope
│       ├── tools/
│       │   ├── registry.py
│       │   ├── read_file.py
│       │   ├── list_directory.py
│       │   ├── search_code.py
│       │   ├── replace_block.py
│       │   ├── run_tests.py
│       │   ├── get_failing.py
│       │   └── finish.py
│       ├── trajectory/
│       │   ├── recorder.py
│       │   └── writer_jsonl.py
│       ├── defects4j/
│       │   ├── checkout.py
│       │   └── verify.py
│       ├── orchestrator/
│       │   └── controller.py
│       └── cli.py                  # apr-agent CLI
├── configs/
│   └── bugs.yaml
├── data/                           # gitignored
├── scripts/
└── tests/
```

### `pyproject.toml` (skeleton)

```toml
[project]
name = "apr-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "openai>=1.40",
    "pydantic>=2.0",
    "pyyaml",
    "typer",
    "rich",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio", "ruff", "mypy"]

[project.scripts]
apr-agent = "apr_agent.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/apr_agent"]
```

### 下游同学安装方式

| 场景 | 命令 |
|-----|-----|
| 同机协作 | `uv pip install -e /home/shared/nlp_project` |
| 跨机（private repo） | `uv pip install "git+ssh://git@github.com/org/nlp_project.git@main"` |

## 5. Data schema (三方契约)

### 5.1 Pydantic models

```python
class BugSample(BaseModel):
    bug_id: str                     # "Math-12"
    project: str                    # "Math"
    bug_number: int
    buggy_checkout_dir: str
    failing_tests: list[str]
    trigger_test_output: str
    loc_hints: dict | None = None

class ToolCall(BaseModel):
    call_id: str
    tool_name: str
    tool_input: dict
    tool_output: str                # stringified, 回给 LLM 的
    tool_meta: dict                 # exit_code, stderr, file_path 等
    started_at: float
    ended_at: float
    is_error: bool

class Turn(BaseModel):
    turn_idx: int
    started_at: float
    ended_at: float
    request: dict                   # 发给 LLM 的完整 body
    response: dict                  # LLM 原始响应
    thinking: str | None = None     # 解析 <think>...</think> 抽出
    usage: dict
    tool_calls: list[ToolCall]

class Event(BaseModel):
    event_id: int
    turn_idx: int
    at: float
    kind: Literal[
        "turn_start", "llm_response", "thinking", "text_block",
        "tool_call_start", "tool_call_end", "error", "turn_end",
        "verify_start", "verify_end",
    ]
    payload: dict

class VerifyResult(BaseModel):
    all_passing: bool
    previously_failing_now_passing: list[str]
    newly_failing: list[str]
    patch_applied: bool
    test_exit_code: int
    runtime_s: float
    raw_output: str                 # 截断

class Trajectory(BaseModel):
    exp_id: str
    bug_id: str
    status: Literal["fixed", "failed", "aborted", "timeout", "error", "running"]
    bug_sample: BugSample
    turns: list[Turn]
    events: list[Event]
    final_patch: str                # unified diff
    verify: VerifyResult | None
    tool_registry: list[dict]
    meta: dict                      # model_name, agent_version, total_tokens,
                                    # total_cost_usd, duration_s, stop_reason,
                                    # started_at, ended_at, env_fingerprint
```

`model_config = ConfigDict(extra="ignore")` 让下游读老数据不炸。

### 5.2 On-disk layout (per bug)

```
data/trajectories/<exp_id>/<bug_id>/
├── meta.json                  # Trajectory header（不含 turns/events）
├── bug_sample.json
├── turns.jsonl                # 每 turn 完成后 append
├── events.jsonl               # 实时 append（O_APPEND），crash 保护
├── tool_registry.json
├── final_patch.diff
├── verify_result.json
└── raw/
    ├── stdout.log
    ├── stderr.log
    └── defects4j_test.log
```

### 5.3 写入顺序（崩溃恢复）

1. 启动：写 `bug_sample.json` + `tool_registry.json` + `meta.json (status="running")`
2. 事件发生：立刻 append `events.jsonl`
3. Turn 完成：append `turns.jsonl`
4. Verify 完成：写 `final_patch.diff` + `verify_result.json`
5. 原子 rename 覆盖 `meta.json`（`status="fixed"/"failed"/...`）

→ `status="running"` 的目录下次 run-batch 自动识别并重跑（先 `mv <bug>/ <bug>.trash-<ts>/`）。

### 5.4 给小模型的 messages 格式

```python
get_turns_as_messages(
    trajectory,
    *,
    include_thinking: bool = False,    # 是否保留 <think>...</think>
    include_system: bool = True,
) -> list[dict]
```

OpenAI chat-template 兼容（role: system/user/assistant/tool，`tool_calls`/`tool_call_id`），直接能拼 SFT dataset。Qwen 的 thinking 是 inline `<think>` 标签，无需 block 转换。

## 6. Tools (7 个)

| Tool | 签名 | 备注 |
|-----|------|-----|
| `read_file` | `(path, start_line=1, end_line=-1) -> str` | 带行号 |
| `list_directory` | `(path, recursive=false, max_entries=200) -> list[str]` | |
| `search_code` | `(pattern, path=".", is_regex=false, max_results=50) -> list[{file,line,content}]` | ripgrep |
| `replace_block` | `(path, old_code, new_code) -> {applied, matches}` | exact search-replace；0 或 ≥2 match 即 fail |
| `run_tests` | `(test_filter=None, timeout_s=300) -> {passing, failing, output_tail}` | `defects4j test` 封装 |
| `get_failing_tests` | `() -> list[str]` | |
| `finish` | `(rationale: str) -> None` | 宣告完成 |

**排除**：通用 shell、git 操作、任意写路径；`replace_block` 硬拒 `*Test*.java` 和 trigger tests。

## 7. Defects4J integration

```python
class Defects4jEnv:
    scratch_root: Path
    defects4j_bin: Path

    def checkout(self, bug_id, run_uuid) -> CheckedOut
    def info(self, bug_id) -> BugInfo

class CheckedOut:
    work_dir: Path
    bug_id: str

    def compile() -> CompileResult
    def run_tests(filter=None, timeout_s=300) -> TestResult
    def current_failing() -> list[str]
    def diff_from_base() -> str          # git diff 作为 final_patch
    def cleanup() -> None
```

Checkout 后立即 `git init + git add + git commit -m "base"`，给 agent 的编辑一个 diff 基准。

## 8. Orchestrator & public API

### 8.1 CLI

```bash
apr-agent run-batch \
    --config configs/bugs.yaml \
    --exp-id baseline-v1 \
    --data-root data/trajectories \
    --concurrency 4
```

### 8.2 `configs/bugs.yaml`

```yaml
model:
  name: qwen3-coder-30b-a3b-instruct
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
  max_tokens: 4096
  temperature: 0.2
  enable_thinking: true

agent:
  max_turns: 30
  overall_timeout_s: 1800
  tool_timeouts:
    run_tests: 300
    replace_block: 10

bugs:
  - Math-12
  - Lang-1
```

### 8.3 Public API (`apr_agent/api.py`)

```python
# Read
def load_trajectory(data_root, exp_id, bug_id) -> Trajectory
def iter_trajectories(data_root, exp_id, *, only_fixed=False,
                      status_in=None, lazy_load_events=False) -> Iterator[Trajectory]
def list_bugs(data_root, exp_id, status_filter=None) -> list[str]
def list_experiments(data_root) -> list[str]
def get_experiment_summary(data_root, exp_id) -> ExperimentSummary

# Transforms
def get_turns_as_messages(trajectory, *, include_thinking=False,
                          include_system=True) -> list[dict]
def get_events_stream(trajectory) -> list[Event]
def get_trajectory_for_summarization(
    trajectory, *, format: Literal["messages","narrative","events"]="messages"
) -> str | list[dict]

# Downstream decomposition read/write
def write_decomposed_steps(data_root, exp_id, bug_id, steps) -> None
def read_decomposed_steps(data_root, exp_id, bug_id) -> list[Step] | None
```

`__init__.py` 只 `from apr_agent.api import *`。

## 9. Error handling & resumption

| 情况 | 行为 |
|-----|------|
| Worker OOM/crash | orchestrator timeout → `status="error"`，下次重跑 |
| API 429 / rate limit | 退出码非零 → AIMD 减并发 + 重入 |
| Defects4J checkout 失败 | `status="error"`, reason="checkout_failed" |
| max_turns 触顶 | `status="failed"`, stop_reason="max_turns" |
| Ctrl-C 中途 | `status="running"` → 下次自动识别并重跑 |
| `fixed`/`failed`/`timeout` | 默认 skip；`--force-rerun` 覆盖 |

重跑前先 `mv <bug>/ <bug>.trash-<ts>/`，保留老数据。

## 10. Testing strategy

- **Unit**：tool 层边界（`replace_block` 的 ambiguous match、`read_file` 行号）、schema 解析器、writer
- **Integration**：FakeLLMClient 跑 agent loop，检查 trajectory 格式
- **Smoke**：用 Chart-1 或 Math-2 端到端跑真 Qwen，`load_trajectory` 能读回
- **Contract test**：下游同学 import 包跑 `iter_trajectories` + `get_turns_as_messages` 通过
- **Coverage 目标 80%**

## 11. Milestones

| M | 内容 | 产物 |
|---|-----|-----|
| M1 (1–2w) | schema + writer + fake LLM end-to-end | fake trajectory 能读回 |
| M2 (1w) | Defects4J env 层 + 真 tool | `defects4j test` 跑通 |
| M3 (1–2w) | agent loop + Qwen client + Chart-1 冒烟 | 真 bug 能被真 Qwen 修好 |
| M4 (1w) | orchestrator + 多 bug + AIMD | 10 个 bug baseline |
| M5 (1w) | 包打磨 + 文档 + 交付 | 下游同学能消费 |
| M6+ | 扩展到 100–835 bugs；DB 迁移/HTTP（可选） | 规模实验 |

## 12. Env fingerprint (reproducibility)

每条轨迹 `meta.env_fingerprint`：

```json
{
  "git_sha": "...",
  "defects4j_version": "2.0.1",
  "java_version": "1.8.0_392",
  "python_version": "3.11.9",
  "apr_agent_version": "0.1.0",
  "model_id": "qwen3-coder-30b-a3b-instruct",
  "host": "..."
}
```

## 13. External dependencies

```bash
# Defects4J
git clone https://github.com/rjust/defects4j
cd defects4j && ./init.sh
export PATH=$PATH:$(pwd)/framework/bin

# Java 8
sudo apt install openjdk-8-jdk

# Python env
uv sync
```

## 14. Open questions / deferred

- **DB 迁移触发条件**：bug 数 > 500 或下游同学有 SQL 查询需求时再做。schema 已预留。
- **HTTP API**：跨机协作出现时再做，接口和 Python lib 一一对应。
- **Cost tracking**：当前只记 `total_tokens` 和 `total_cost_usd`；细粒度 per-turn cost 等有需求再加。
- **防作弊 v2**：目前只禁改测试文件，未检测 agent 通过 reflection 绕测试逻辑。短期不做。
