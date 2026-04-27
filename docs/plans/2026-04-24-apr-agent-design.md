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
    trigger_tests: list[str]        # defects4j export -p tests.trigger (authoritative)
    currently_failing: list[str]    # observed after checkout (may be superset of trigger_tests)
    trigger_test_output: str
    defects4j_version: str          # e.g. "2.0.1"
    d4j_subset: str | None = None   # e.g. "1.2" / "2.0" — which academic slice this bug belongs to
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
    request: dict                   # 发给 LLM 的完整 body（API key 等敏感字段 M3 里 mask 掉）
    response: dict                  # {"parsed": {"content", "stop_reason", "tool_calls"},
                                    #  "raw": <provider-native dump>}
                                    # parsed 是稳定契约，raw 不保证 shape
    thinking: str | None = None     # message.reasoning_content（DashScope thinking models）
                                    # 或 inline <think>...</think>。qwen3.5-plus 走前者
    usage: dict                     # MUST contain {"prompt_tokens", "completion_tokens"}
                                    # 缺项填 0，不得省略——per-turn cost 归因必需
    tool_calls: list[ToolCall]
    regression_summary: dict | None = None   # schema 1.1+；从该 turn 最后一次成功的
                                    # run_tests tool_meta 里抽出。形如：
                                    # {"currently_failing": [...], "newly_failing": [...],
                                    #  "still_failing": [...], "now_passing": [...]}
                                    # None = 该 turn 没有成功的 run_tests

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

**Schema 版本**：`meta.json` 里写 `"schema_version": "<major>.<minor>"`，当前 `"1.1"`。`load_trajectory` 遇到不认识的 major 号直接 raise。`extra="ignore"` 只扛加字段，扛不住 rename/删字段/语义变化，必须靠显式版本号。

变更日志：
- **1.1**（v0.4.0）：`Turn.regression_summary` 字段（additive，可选）；`RunTestsTool` 的 `tool_meta` 加 `currently_failing`/`newly_failing`/`still_failing`/`now_passing`；新增 `get_current_diff` tool。
- 1.0（v0.1.0–v0.3.x）：M1 初始版本。

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

**粒度：turn 级持久化。** 单个 turn 内的事件（`llm_response` / `tool_call_*` / `turn_end`）在 turn 结束时批量 append。原因是 M1 的 loop 不直接持有 recorder，事件由 `record_turn` 统一派生。代价是：如果 worker 在 tool 调用中途被 kill（例如 `run_tests` 超时、JVM OOM），当前 turn 的事件完全丢失。

**后续**（M3 接真 tool 时）：若该代价不能接受，把 recorder 注入 AgentLoop，`tool_call_start/end` 在 invoke 前后实时 emit。M1 先冻 schema，loop 内部结构可以后改，schema 不变。

1. 启动：写 `bug_sample.json` + `tool_registry.json` + `meta.json (status="running", schema_version="1.0")`
2. Turn 完成：先 append `turns.jsonl`，再 append 本 turn 的派生事件到 `events.jsonl`（顺序很重要——崩在中间时要么两边都有，要么只剩 turn 记录，没有「有事件无 turn」的脏状态）
3. Verify 完成：写 `final_patch.diff` + `verify_result.json`
4. 原子 rename 覆盖 `meta.json`（`status="fixed"/"failed"/...`）

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

OpenAI chat-template 兼容（role: system/user/assistant/tool，`tool_calls`/`tool_call_id`），直接能拼 SFT dataset。

**TODO (M3 待验证)**：Qwen thinking 的载体形式依赖具体端点和模型变体：
- 自部署 Qwen3-Thinking：inline `<think>...</think>`
- DashScope OpenAI-compatible 端点（`reasoning_content` 单独字段）对 `qwen3-coder-30b-a3b-instruct` 这个 `-Instruct` 变体到底支持不支持、`enable_thinking: true` 是被接受还是被忽略/报错，**未验证**

M3 第一步先跑 `scripts/qwen_smoke.py`：单轮 chat，完整打印 response JSON 原样，确认字段形状再写 parser。别预先押注。

## 6. Tools (8 个)

| Tool | 签名 | 备注 |
|-----|------|-----|
| `read_file` | `(path, start_line=1, end_line=-1) -> str` | 带行号；gutter 用 `\| ` 分隔（`123\| <content>`），让 indent 边界对 LLM 不歧义 |
| `list_directory` | `(path, recursive=false, max_entries=200) -> list[str]` | 自动跳过 `.git`/`build`/`target` 等 |
| `search_code` | `(pattern, path=".", is_regex=false, max_results=50) -> list[{file,line,content}]` | ripgrep 优先，缺则 pure-Python 回退 |
| `replace_block` | `(path, old_code, new_code) -> {applied, matches}` | exact search-replace；0 或 ≥2 match 即 fail；deny-list = trigger test 路径硬禁 |
| `run_tests` | `(test_filter=None, timeout_s=300) -> {currently_failing, newly_failing, still_failing, now_passing, output_tail}` | `defects4j test` 封装；输出**显式 partition 当前失败 vs baseline trigger tests**——agent 能直接看到自己引入的回归 |
| `get_failing_tests` | `() -> list[str]` | 优先读 cached `failing_tests` 文件 |
| `get_current_diff` | `() -> str` | **schema 1.1+**。返回累计 `git diff HEAD`（cap 30K），让 agent 不必 `read_file` 重读就能看到自己改了什么 |
| `finish` | `(rationale: str) -> None` | 宣告完成 |

**错误反馈契约**：所有 tool 在 `is_error=True` 路径下，错误描述同时写到 `tool_output`（LLM 看见的）和 `tool_meta["error"]`（结构化）。LLM 永远不会拿到空字符串然后猜原因——这是 v0.4.0 修复的关键 UX bug，把 JacksonDatabind-1 从 93 turn 降到 14 turn。

**排除**：通用 shell、git 操作、任意写路径。

**`replace_block` 防作弊 deny-list**（M2 已实现）：worker 启动时调 `defects4j export -p tests.trigger` 拿权威 trigger test 路径，由 `trigger_test_files()` 把测试 id 翻译成 `src/test/...` 路径并注入 `ReplaceBlockTool(work_dir, protected_paths=...)`。**不用 `*Test*.java` 正则**——会漏 `*IT.java`/`*Spec.java`，会误伤 `TestUtils.java`。

**`run_tests` 回归识别**（M3+ 实现）：worker 启动时把 `BugSample.trigger_tests` 当作 baseline failing set 传给 `RunTestsTool(baseline_failing=...)`。每次 invoke 后 partition：
- `newly_failing` = currently \ baseline（agent 引入的回归）
- `still_failing` = currently ∩ baseline（trigger 还没修好）
- `now_passing` = baseline \ currently（trigger 已修好）

LLM 直接在 tool_output 里看到这个 partition，不用自己对历史 list 做 diff。

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
  enable_thinking: true         # M3 待验证实际是否被 DashScope 接受，见 §5.4 TODO

agent:
  max_turns: 30
  overall_timeout_s: 1800
  tool_timeouts:
    run_tests: 300
    replace_block: 10

dataset:
  defects4j_version: "2.0.1"    # semver；main 分支在动，务必锁
  defects4j_commit_sha: null    # 可选；填了以它为准
  d4j_subset: "2.0"             # "1.2" = 经典 APR baseline (395 bugs, 6 projects)
                                # "2.0" = 现代切片 (835 bugs, 17 projects)

bugs:
  # 显式 bug id；`apr-agent` 启动时会和 `defects4j bids -p <project>` 拿到的
  # active list 做交叉校验，命中 deprecated 的直接 warn + skip
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

| M | 状态 | 内容 | 产物 |
|---|---|-----|-----|
| M1 | ✅ v0.1.0-m1 | schema 1.0 + writer + fake LLM end-to-end | fake trajectory 能读回 |
| M2 | ✅ v0.3.0-m3 | Defects4J env 层 + 7 个真 tool | `defects4j test` 跑通 |
| M3 | ✅ v0.3.0-m3 | agent loop + Qwen client + 真 bug 修复 | 13 fixed trajectories（v0.3.1） |
| M3+ | ✅ v0.4.0 | schema 1.1（regression_summary）+ get_current_diff tool + 错误反馈 fix + 并发 orchestrator | 16 fixed trajectories 跨 16 项目 |
| M4 | 🔜 | AIMD scheduler + retry/resume + scratch GC | 100+ bug baseline |
| M5 | 🔜 | 包打磨 + 文档 + 交付 | 下游同学能消费 |
| M6+ | future | 扩展到 800+ bugs；DB 迁移（design §15）/HTTP（可选） | 规模实验 |

## 12. Env fingerprint (reproducibility)

每条轨迹 `meta.env_fingerprint`：

```json
{
  "git_sha": "...",
  "defects4j_version": "2.0.1",
  "defects4j_commit_sha": "...",
  "d4j_subset": "2.0",
  "java_version": "1.8.0_392",
  "tz": "America/Los_Angeles",
  "python_version": "3.11.9",
  "apr_agent_version": "0.1.0",
  "model_id": "qwen3-coder-30b-a3b-instruct",
  "host": "..."
}
```

**时区强制**：Defects4J 在 `America/Los_Angeles` 时区生成/执行测试，部分 bug 的 trigger test 对时区敏感。worker subprocess 启动前必须 `export TZ=America/Los_Angeles`（在 M3 的 `agent/worker.py` 里做），不然会诡异失败。fingerprint 里记下来是为了防止谁漏 export 后事后甩锅找不到原因。

**版本锁**：`defects4j_version` 是 semver（如 `2.0.1`），`defects4j_commit_sha` 是具体 commit。主分支 active-bugs 数量一直在动（当前 main 已到 854），**必须锁 commit**，版本号只是辅助可读性。

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

## 14. Evaluation protocol notes

**Oracle-access 设定**：agent 在 run 中可以调 `run_tests` 拿到实时 pass/fail 反馈，属于 **oracle-access** 设定。下游小模型同学训练完做 eval 也**必须**在 oracle-access 下评测（同样暴露 `run_tests`），否则训练/评测分布错配，结论不成立。

**不作弊约束**：即便是 oracle-access，agent 也不允许改测试文件（`replace_block` 通过 `trigger_tests` 路径做硬 deny-list）、不允许用 reflection 绕 assertion（v2 防作弊，短期不做）。

## 15. Open questions / deferred

- **DB 迁移触发条件**：bug 数 > 500 或下游同学有 SQL 查询需求时再做。schema 已预留。
- **HTTP API**：跨机协作出现时再做，接口和 Python lib 一一对应。
- **Cost tracking**：当前只记 `total_tokens` 和 `total_cost_usd`；细粒度 per-turn cost 等有需求再加。
- **防作弊 v2**：目前只禁改测试文件，未检测 agent 通过 reflection 绕测试逻辑。短期不做。
