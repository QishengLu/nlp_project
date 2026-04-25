# apr-agent

LLM agent 在 Defects4J 上自动修 Java bug，把每次修复的完整过程（每一轮 LLM 请求/回应、调过的 tool、最终 patch、独立验证结果）按稳定 schema 落盘成 trajectory，供下游做 step 拆分 / 小模型蒸馏。

当前版本：v0.3.1，附带 13 条已验证的 fixed trajectory，覆盖 9 个项目（Math、Lang、Mockito、Cli、Csv、Gson、JxPath、Jsoup、Codec）。

---

## 你是哪种用户？

**A. 我只想读 trajectory 数据，做总结/训练** → 看下面 [给下游同学](#给下游同学只读-trajectory)
**B. 我想自己跑 agent 产生新 trajectory** → 看 [给 producer](#给-producer想自己跑-agent)
**C. 我想看设计 / 改源码** → 看 [设计与契约](#设计与契约)

---

## 给下游同学（只读 trajectory）

只需要 Python ≥ 3.11，不需要 Java、Defects4J、API key——这些都是产数据时才用的。

### 装包（推荐：git clone，连数据一起拿）

```bash
git clone https://github.com/QishengLu/nlp_project.git
cd nlp_project
uv venv --python 3.11 && source .venv/bin/activate
uv pip install -e .
```

`data/trajectories/` 跟代码一起 clone 下来，下面所有示例的 `data_root="data"` 直接生效。

> 也可以只装包不要数据：`uv pip install "git+https://github.com/QishengLu/nlp_project.git@v0.3.1-trajectories"`，这样 trajectory 你得自己想办法拿（git clone 单独的 `data/` 目录、wget 文件、或者从同事那拷一份），把 `data_root` 指过去即可。

### 最小用法

```python
import apr_agent

# 列出有哪些实验、哪些 bug
apr_agent.list_experiments("data")               # ["batch-1", "batch-2", "smoke-4"]
apr_agent.list_bugs("data", "batch-2")           # ["Cli-11", "Codec-2", "Csv-11", ...]

# 读一条
tr = apr_agent.load_trajectory("data", "batch-2", "Mockito-29")
tr.status                                         # "fixed"
tr.verify.all_passing                             # True
tr.bug_sample.trigger_tests                       # ["org.mockitousage.....::test"]
len(tr.turns)                                     # 15

# 全部 fixed 的导成 OpenAI chat-template messages，直接喂 SFT
for tr in apr_agent.iter_trajectories("data", "batch-2", only_fixed=True):
    msgs = apr_agent.get_turns_as_messages(tr, include_thinking=True)
    # msgs = [{"role":"system",...}, {"role":"user",...}, {"role":"assistant",...}, {"role":"tool",...}, ...]

# 写回拆完的步骤（你拆完之后存这里）
apr_agent.write_decomposed_steps("data", "batch-2", "Mockito-29", [
    {"step_id": 1, "kind": "locate", "summary": "..."},
    ...
])
```

更多用法见 [tests/test_contract_downstream.py](tests/test_contract_downstream.py)——这个文件就是给你们的 API 清单，里面调用的方法都是稳定接口。

### 公开 API 一览

只能依赖 `apr_agent` 包根下导出的这些，其它子模块（`agent/`、`tools/`、`defects4j/` 等）算实现细节，可能改：

| 类型 | 名字 |
|---|---|
| Schema | `Trajectory`, `Turn`, `Event`, `ToolCall`, `BugSample`, `VerifyResult`, `ExperimentSummary`, `SchemaVersionError` |
| 读 | `load_trajectory`, `iter_trajectories`, `list_bugs`, `list_experiments` |
| 转换 | `get_turns_as_messages` (OpenAI chat-template), `get_events_stream`, `get_trajectory_for_summarization` |
| 统计 | `get_experiment_summary` |
| 写下游产出 | `write_decomposed_steps`, `read_decomposed_steps` |

### 数据集说明

13 条 fixed trajectory 在 [data/trajectories/](data/trajectories/) 下，按 `<exp_id>/<bug_id>/` 组织：

| 实验 | 项目 × bug |
|---|---|
| `smoke-4` | Math-50 |
| `batch-1` | Math-3, Math-70, Lang-21, Lang-33, Lang-55 |
| `batch-2` | Mockito-29, Cli-11, Csv-11, Gson-15, JxPath-22, Jsoup-26, Codec-2 |

每个 bug 目录里：

```
<exp>/<bug_id>/
├── meta.json              ← status="fixed", schema_version, env_fingerprint, 时间统计
├── bug_sample.json        ← BugSample (trigger_tests, defects4j_version, ...)
├── tool_registry.json     ← agent 看到的 7 个 tool 的 OpenAI function schema
├── turns.jsonl            ← 每行一个 Turn (request + response + tool_calls + usage)
├── events.jsonl           ← 每行一个 Event（细粒度时间线）
├── final_patch.diff       ← agent 改完之后 git diff HEAD 的产物（"答案"）
└── verify_result.json     ← 独立 fresh checkout 验证结果（all_passing=true, ...）
```

详细字段定义见 [docs/plans/2026-04-24-apr-agent-design.md §5](docs/plans/2026-04-24-apr-agent-design.md)。

### 版本契约

`meta.schema_version="1.0"` 是冻结的契约。我升 schema 主版本会:

1. 在 `apr_agent/__init__.py` 里 bump
2. `load_trajectory` 自动 raise `SchemaVersionError`，老数据不会被静默升级
3. 推送前发群通知

---

## 给 producer（想自己跑 agent）

需要：JDK 8、Defects4J、`DASHSCOPE_API_KEY`（DashScope OpenAI 兼容端点）。

### 一次性 bootstrap

```bash
git clone https://github.com/QishengLu/nlp_project.git
cd nlp_project
bash scripts/bootstrap_vendor.sh        # ~5 分钟，下 ~1.8GB（JDK + D4J + Perl 模块）到 vendor/
uv venv --python 3.11
source scripts/activate_env.sh          # 激活 venv + 设 PATH/JAVA_HOME/TZ
uv pip install -e ".[dev]"
```

### 配 API key

```bash
echo "DASHSCOPE_API_KEY=sk-..." > .env
chmod 600 .env
```

`.env` 已在 `.gitignore` 里，不会提交。

### 跑一批

```bash
source scripts/activate_env.sh
set -a; source .env; set +a

apr-agent run-batch \
    --config configs/bugs.yaml \
    --exp-id my-exp-1 \
    --data-root data \
    --scratch-root scratch \
    --bugs Math-3,Math-50,Lang-33

apr-agent summary --exp-id my-exp-1
```

`configs/bugs.yaml` 默认配 `qwen3.5-plus` + max_turns=60。改 `bugs:` 字段或用 `--bugs A,B,C` 覆盖。

### 看实时进度

```bash
tail -f logs/*.log                      # 自己 nohup 时
apr-agent summary --exp-id my-exp-1     # 任何时候查总数
```

### 已知项目限制

- **Chart 项目跑不了**：D4J 用 SVN repo 装它，bootstrap 脚本不装 svn 客户端。其他 16 个项目都能跑。
- **Closure 项目编译慢**：单个 bug 经常 5+ 分钟，`--overall-timeout-s` 设 1500+ 比较稳。

---

## 设计与契约

| 文档 | 内容 |
|---|---|
| [docs/plans/2026-04-24-apr-agent-design.md](docs/plans/2026-04-24-apr-agent-design.md) | 总体设计：架构、schema、tool 列表、verify、防作弊 |
| [docs/plans/2026-04-24-apr-agent-m1-foundation.md](docs/plans/2026-04-24-apr-agent-m1-foundation.md) | M1 实现 plan（taskwise） |
| [tests/test_contract_downstream.py](tests/test_contract_downstream.py) | 公开 API 的契约测试，"我能调什么" 的金标准 |
| [data/trajectories/README.md](data/trajectories/README.md) | 13 条 trajectory 的 manifest |

---

## 开发

```bash
uv pip install -e ".[dev]"
uv run pytest                            # 全量测试，~80s（含 D4J integration）
uv run pytest -m "not defects4j"         # 跳过需要 D4J 的，~3s
uv run pytest --cov=apr_agent            # 覆盖率
uv run ruff check .                      # lint
```

103 个 unit + integration test，95% 覆盖率（不含 d4j-integration / live-API 的 gated 路径）。

---

## 版本与状态

- **v0.1.0-m1**: schema + JSONL writer + Fake LLM e2e
- **v0.3.0-m3**: 真 tools + Defects4J env + Qwen client + subprocess worker + orchestrator
- **v0.3.1-trajectories**（当前）: 同上 + 13 条 fixed trajectory

下一步路线见 [docs/plans/2026-04-24-apr-agent-design.md §11](docs/plans/2026-04-24-apr-agent-design.md)（M4 = AIMD 并发，M5 = 文档/交付，M6+ = 扩到 100+ bug 时切 SQLite）。
