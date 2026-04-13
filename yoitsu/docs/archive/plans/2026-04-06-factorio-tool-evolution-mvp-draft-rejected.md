# Factorio Tool Evolution MVP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 yoitsu 自主演化出一个 Factorio Lua 脚本。第一个 driving task 故意需要重复调用单点 atomic 工具；observation 信号捕获重复模式；reviewer 提议新增一个 action 脚本；implementer 任务在 evo 仓库中写出该脚本并 commit；第二次执行同一 task 时 worker 自动使用新脚本，工具调用次数显著下降。

**Architecture:**
- factorio-agent 仓库本身充当 yoitsu 的 evo（选项 3），通过 `teams/factorio/` 子目录承载所有 role/tool/context 定义。
- worker（team=factorio，串行锁）只暴露一个 `factorio_call_script` dispatcher tool；脚本目录通过 context_fn 注入 system prompt。
- implementer（team=default，可并发）持有普通文件工具，写权限通过 publication_fn 路径白名单限定到 `teams/factorio/scripts/`。
- 引入两个新 observation 信号 `observation.tool_repetition` 和 `observation.context_late_lookup`，在 interaction loop 出口扫描 tool_call 历史 emit。所有信号字段单层（Pasloe 表结构约束）。
- reviewer 周期性拉取 `observation.*` 事件，按 kind 分桶分析，输出 ReviewProposal；review loop 输出闭环已在 supervisor.py:1678 实现，本计划不动。

**Tech Stack:** Python, Pydantic, factorio-rcon (Source RCON 协议), yoitsu-contracts (Observation 模型), palimpsest (runtime/interaction/contexts), Lua（factorio mod 端）

**Non-goals:**
- 不实现 factorio 服务器自动部署（假设 host 已有 factorio-agent 现成的 systemd / 手动启动）
- 不动 factorio-agent 的 mod 实现（mod 端的 dynamic_scripts 热重载已经够用）
- 不引入 ArtifactStore checkpoint（留给后续 Phase 3 stateful domain validation）
- 不删除 factorio-agent 的 `agent/loop.py` 等独立运行入口（保留为 fallback，等 MVP 跑通后再 deprecate）

---

## Task 1: 扩展 observation 信号合约

**Files:**
- Modify: `yoitsu-contracts/src/yoitsu_contracts/observation.py`
- Modify: `yoitsu-contracts/tests/test_observation.py`

**Step 1: 添加两个新事件类型常量**

在 `observation.py` 顶部常量区追加：

```python
OBSERVATION_TOOL_REPETITION = "observation.tool_repetition"
OBSERVATION_CONTEXT_LATE_LOOKUP = "observation.context_late_lookup"
```

**Step 2: 添加两个 flat-field Pydantic 模型**

```python
class ToolRepetitionData(BaseModel):
    """Emitted when a single tool was called many times in one job with similar args.

    All fields single-layer per Pasloe domain table constraint.
    """
    job_id: str
    task_id: str
    role: str
    team: str
    tool_name: str
    call_count: int
    arg_pattern: str       # 字符串摘要，如 "grid_5x2"、"sequential_x_axis"
    similarity: float      # 0.0-1.0，调用之间参数结构相似度

class ContextLateLookupData(BaseModel):
    """Emitted when a job repeatedly used a query tool whose answers
    could plausibly have been provided up-front by context_fn.
    """
    job_id: str
    task_id: str
    role: str
    tool_name: str         # 例如 "pasloe.query"
    call_count: int
    query_kind: str        # 字符串摘要，如 "events_in_last_task"
```

**Step 3: 单元测试**

在 `tests/test_observation.py` 加：
- `test_tool_repetition_data_flat_fields()` — 校验所有字段 primitive
- `test_context_late_lookup_data_flat_fields()` — 同上
- `test_observation_event_type_constants()` — 校验前缀都是 `observation.`

**Verification:**
```bash
cd yoitsu-contracts && uv run pytest tests/test_observation.py -v
```
预期：5 个新增 / 修改的测试通过。

---

## Task 2: 在 interaction loop 出口扫描并 emit 新信号

**Files:**
- Modify: `palimpsest/palimpsest/stages/interaction.py`
- Modify: `palimpsest/palimpsest/runtime/event_gateway.py`(若需添加 emit helper)
- Add: `palimpsest/palimpsest/runtime/tool_pattern.py`(纯函数模块)
- Modify: `palimpsest/tests/test_interaction.py`(或新建测试)

**Step 1: 写 tool_pattern 检测纯函数**

新建 `palimpsest/palimpsest/runtime/tool_pattern.py`：

```python
"""Tool-call pattern detectors used at job end to emit observation signals.

Pure functions over tool call history. No I/O, no event emission here —
the caller (interaction stage) decides which signals to emit.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ToolCallRecord:
    name: str
    args_json: str   # serialized for similarity scoring


@dataclass
class RepetitionFinding:
    tool_name: str
    call_count: int
    arg_pattern: str
    similarity: float


def detect_repetition(
    history: list[ToolCallRecord],
    *,
    min_count: int = 5,
    similarity_threshold: float = 0.7,
) -> list[RepetitionFinding]:
    """Find tools called >= min_count times with high arg-structure similarity.

    Returns one finding per (tool_name) that crosses the threshold.
    Empty list if nothing notable.
    """
    # group by tool name; for each group with len >= min_count,
    # compute pairwise structural similarity (key-set overlap is sufficient
    # for MVP — no need for value-level diff). If avg similarity >= threshold,
    # produce one finding.
    ...


@dataclass
class LateLookupFinding:
    tool_name: str
    call_count: int
    query_kind: str


# 已知的 "查询型" 工具名集合 — MVP 写死，后续可改成元数据
LATE_LOOKUP_TOOLS = {
    "pasloe.query",
    "pasloe.search",
    # 加入后再扩
}


def detect_late_lookup(
    history: list[ToolCallRecord],
    *,
    min_count: int = 3,
) -> list[LateLookupFinding]:
    """Find query-type tools called >= min_count times in one job."""
    ...
```

**Step 2: 在 interaction stage 出口调用检测器**

在 `interaction.py` 的 interaction loop 完成后（job 即将进入 publication 之前），调用：

```python
from palimpsest.runtime.tool_pattern import detect_repetition, detect_late_lookup

repetitions = detect_repetition(tool_call_history)
for r in repetitions:
    gateway.emit_observation(
        event_type="observation.tool_repetition",
        data={
            "job_id": ctx.job_id,
            "task_id": ctx.task_id,
            "role": role_name,
            "team": ctx.team,
            "tool_name": r.tool_name,
            "call_count": r.call_count,
            "arg_pattern": r.arg_pattern,
            "similarity": r.similarity,
        },
    )

late_lookups = detect_late_lookup(tool_call_history)
for l in late_lookups:
    gateway.emit_observation(
        event_type="observation.context_late_lookup",
        data={
            "job_id": ctx.job_id,
            "task_id": ctx.task_id,
            "role": role_name,
            "tool_name": l.tool_name,
            "call_count": l.call_count,
            "query_kind": l.query_kind,
        },
    )
```

注意 `tool_call_history` 必须是 interaction loop 实际维护的列表 —— 如果当前没有，本步骤要先在 loop 内加一个累加器（每次 tool 调用 append `ToolCallRecord(name, json.dumps(args, sort_keys=True))`）。

**Step 3: 单元测试**

`palimpsest/tests/test_tool_pattern.py`：
- `test_detect_repetition_above_threshold` — 构造 10 次相同结构的调用
- `test_detect_repetition_below_threshold` — 4 次调用，无 finding
- `test_detect_repetition_dissimilar_args` — 10 次但参数结构差异大，无 finding
- `test_detect_late_lookup` — 4 次 `pasloe.query` 调用 → 1 finding
- `test_detect_late_lookup_unknown_tool` — 100 次未知工具 → 无 finding

`palimpsest/tests/test_interaction_observation_emit.py`：
- 一个 mock interaction loop 跑完，断言 gateway 收到了对应的 observation.* 事件，且字段全单层。

**Verification:**
```bash
cd palimpsest && uv run pytest tests/test_tool_pattern.py tests/test_interaction_observation_emit.py -v
```

---

## Task 3: 让 context provider loader 支持 team 子目录

**Files:**
- Modify: `palimpsest/palimpsest/runtime/contexts.py`
- Modify: `palimpsest/tests/test_contexts.py`

**Step 1: 修改 resolve_context_functions 签名加 team 参数**

```python
def resolve_context_functions(
    evo_root: str | Path,
    requested: list[str],
    team: str = "default",
) -> dict[str, Callable]:
    """Scan evo/teams/<team>/contexts/*.py first (overrides),
    then fall back to evo/contexts/*.py for any unresolved sections.
    Resolution order matches RoleManager (ADR-0011)."""
```

**Step 2: 实现 team-first 解析**

```python
result: dict[str, Callable] = {}
team_scan = Path(evo_root) / "teams" / team / "contexts"
global_scan = Path(evo_root) / "contexts"

for scan_dir in (team_scan, global_scan):  # team first
    if not scan_dir.is_dir():
        continue
    for py_file in sorted(scan_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        funcs = _load_context_functions(py_file)
        for section_type, func in funcs.items():
            if section_type in requested_set and section_type not in result:
                result[section_type] = func
```

**Step 3: 调用方传入 team**

grep 所有 `resolve_context_functions(` 的调用点，传入当前 job 的 team（应该在 `runner.py` 或 `runtime/roles.py` 中已经可达）。

**Step 4: 测试**

`palimpsest/tests/test_contexts.py` 增加：
- `test_team_context_overrides_global` — fixture 中 team 和 global 都定义同一 section_type，team 版本被选中
- `test_team_context_extends_global` — team 只定义 A，global 定义 B，最终拿到 A+B
- `test_no_team_dir_falls_back_to_global` — team 目录不存在时正常回退

**Verification:**
```bash
cd palimpsest && uv run pytest tests/test_contexts.py -v
```

---

## Task 4: 让 evo_root 支持指向 factorio-agent 仓库

**Files:**
- Read-only: `palimpsest/palimpsest/runner.py:68,393` (理解 `_EVO_DIR` 当前 hard-code)
- Modify: `palimpsest/palimpsest/runner.py`
- Modify: `palimpsest/palimpsest/config.py`(若 evo_root 配置入口在这里)
- Modify: `trenni/trenni/runtime_builder.py`(若注入 evo path 在这里)

**Step 1: 把 `_EVO_DIR` 从常量改为可配置**

```python
# 旧：
_EVO_DIR = "evo"
# 新：通过环境变量或配置覆盖
_EVO_DIR = os.environ.get("PALIMPSEST_EVO_DIR", "evo")
```

container 内的工作目录约定为 `/work`，evo 默认挂在 `/work/evo`。如果用户把 factorio-agent clone 到 `/work/evo`，行为不变。如果想复用现有 factorio-agent 仓库，可以挂到任意路径并用 `PALIMPSEST_EVO_DIR=/abs/path/to/factorio-agent` 覆盖。

**Step 2: 在 trenni 的 quadlet/容器配置中传 PALIMPSEST_EVO_DIR**

在 `deploy/quadlet/trenni.dev.yaml` 加 factorio team 段：

```yaml
teams:
  factorio:
    runtime:
      image: localhost/yoitsu-palimpsest-job:dev
      env_allowlist:
        - PALIMPSEST_EVO_DIR
        - FACTORIO_RCON_HOST
        - FACTORIO_RCON_PORT
        - FACTORIO_RCON_PASSWORD
      extra_networks:
        - factorio-net
    scheduling:
      max_concurrent_jobs: 1
```

env 的实际值在 `trenni.env.example` 中说明，部署者负责在 `.env` 中填实际路径与 RCON 凭据。

**Step 3: 测试**

不写新单元测试。这一步的验收靠 Task 9 的端到端 smoke。

**Verification:**
```bash
PALIMPSEST_EVO_DIR=/tmp/fake-evo python -c "from palimpsest.runner import _EVO_DIR; print(_EVO_DIR)"
# 输出：/tmp/fake-evo
```

---

## Task 5: 重组 factorio-agent 仓库，铺出 evo 目录结构

**Repo:** `/home/holo/factorio-agent`（独立 git repo，本任务在该仓库内提交）

**Files (新建):**
- `teams/factorio/lib/__init__.py`
- `teams/factorio/lib/rcon.py` ← 从 `agent/rcon.py` 移动
- `teams/factorio/lib/bridge.py` ← 从 `agent/bridge.py` 移动
- `teams/factorio/roles/__init__.py`
- `teams/factorio/roles/worker.py`
- `teams/factorio/roles/implementer.py`
- `teams/factorio/tools/__init__.py`
- `teams/factorio/tools/factorio_call_script.py`
- `teams/factorio/tools/api_search.py`
- `teams/factorio/contexts/__init__.py`
- `teams/factorio/contexts/factorio_scripts.py`
- `teams/factorio/prompts/worker.md`
- `teams/factorio/prompts/implementer.md`
- `teams/factorio/scripts/`（从 `mod/scripts/` 镜像 / 移动 — 见下）

**Step 1: 物理移动 RCON 与 bridge**

```bash
git mv agent/rcon.py teams/factorio/lib/rcon.py
git mv agent/bridge.py teams/factorio/lib/bridge.py
```

更新 `agent/loop.py`、`agent/run.py` 等仍引用旧路径的文件（这些仍然作为 standalone fallback 保留），改为 `from teams.factorio.lib.rcon import RCONClient`。

**Step 2: scripts/ 目录的归属**

mod 的 dynamic_scripts 注入需要原始 .lua 源码。两种放法：
- (a) 把 `mod/scripts/` 物理移动到 `teams/factorio/scripts/`，mod 端的 control.lua 改成在启动时从 RCON `register` 接口接收，不再读磁盘 → 改动太大
- (b) **保留 `mod/scripts/` 作为运行时数据源不动，只在 `teams/factorio/scripts/` 加一个 symlink 指向 `../../mod/scripts/`**

选 (b)。implementer 任务的 publication 路径白名单允许写 `teams/factorio/scripts/`（即 `mod/scripts/`），mod 端无任何修改。

```bash
mkdir -p teams/factorio
ln -s ../../mod/scripts teams/factorio/scripts
```

**Step 3: 提交结构**

```bash
git add teams/ agent/
git commit -m "restructure: introduce yoitsu evo layout under teams/factorio/"
```

后续 Task 6/7/8 在该结构下填充实际内容。

**Verification:**
```bash
test -L teams/factorio/scripts && echo "symlink ok"
test -f teams/factorio/lib/rcon.py && echo "rcon moved"
python -c "import sys; sys.path.insert(0, '.'); from teams.factorio.lib.rcon import RCONClient; print(RCONClient)"
```

---

## Task 6: 实现 worker role + factorio_call_script tool + scripts context

**Repo:** `/home/holo/factorio-agent`

**Files:**
- `teams/factorio/roles/worker.py`
- `teams/factorio/tools/factorio_call_script.py`
- `teams/factorio/contexts/factorio_scripts.py`
- `teams/factorio/prompts/worker.md`

**Step 1: factorio_call_script tool**

```python
"""Worker 在游戏内调用 mod 已注册脚本的唯一入口。
所有 Lua 执行都走这一个工具；脚本本身在 evo 中演化。"""
from palimpsest.runtime.tools import tool, ToolResult
from palimpsest.runtime.context import RuntimeContext


@tool
def factorio_call_script(
    name: str,
    args: str = "",
    runtime_context: RuntimeContext = None,
) -> ToolResult:
    """Call a registered Factorio mod script via RCON.

    Args:
        name: script name, e.g. 'atomic.place', 'actions.move'
        args: argument string (typically JSON) understood by the script
    """
    if runtime_context is None or "rcon" not in runtime_context.resources:
        return ToolResult(success=False, output="No RCON connection in runtime context")

    rcon = runtime_context.resources["rcon"]
    raw = rcon.send_command(f"/agent {name} {args}".strip())

    # 注意：RCON 单包 ~4KB 上限。如果 raw 超长，返回截断标志让 LLM 知道。
    truncated = len(raw.encode("utf-8")) >= 4000
    return ToolResult(
        success=True,
        output=raw,
        meta={"truncated": truncated} if truncated else None,
    )
```

**Step 2: factorio_scripts context provider**

```python
"""扫描 evo/teams/factorio/scripts/ 注入脚本目录到 system prompt。"""
from pathlib import Path
import re
from palimpsest.runtime.contexts import context_provider


@context_provider("factorio_scripts")
def factorio_scripts(*, evo_root, **_):
    scripts_dir = Path(evo_root) / "teams" / "factorio" / "scripts"
    catalog = []
    for lua_path in sorted(scripts_dir.rglob("*.lua")):
        rel = lua_path.relative_to(scripts_dir).with_suffix("")
        name = str(rel).replace("/", ".")
        # 提取首行注释作为描述
        first_line = lua_path.read_text(encoding="utf-8").splitlines()[:1]
        desc = ""
        if first_line and (m := re.match(r"--\s*(.+)", first_line[0])):
            desc = m.group(1).strip()
        catalog.append(f"- `{name}` — {desc}" if desc else f"- `{name}`")
    return {"factorio_scripts": "\n".join(catalog)}
```

**Step 3: worker role**

```python
from palimpsest.runtime.roles import role, JobSpec, context_spec
from teams.factorio.lib.rcon import RCONClient
import os


def factorio_worker_preparation(*, runtime_context, **params):
    """Connect RCON, register all evo scripts via /agent register, store in ctx."""
    rcon = RCONClient(
        host=os.environ["FACTORIO_RCON_HOST"],
        port=int(os.environ["FACTORIO_RCON_PORT"]),
        password=os.environ["FACTORIO_RCON_PASSWORD"],
    )
    rcon.connect()
    runtime_context.resources["rcon"] = rcon
    runtime_context.register_cleanup(rcon.close)

    # Register every script under teams/factorio/scripts/ into mod dynamic_scripts
    from pathlib import Path
    scripts_dir = Path(runtime_context.resources.get("evo_root", ".")) / "teams" / "factorio" / "scripts"
    for lua_path in scripts_dir.rglob("*.lua"):
        rel = lua_path.relative_to(scripts_dir).with_suffix("")
        name = str(rel).replace("/", ".")
        code = lua_path.read_text(encoding="utf-8")
        rcon.send_command(f"/agent register {name} <<<{code}>>>")

    # 不需要 git workspace；返回一个 no-op workspace config
    from palimpsest.config import WorkspaceConfig
    return WorkspaceConfig(repo="", new_branch=False)


def factorio_worker_publication(*, runtime_context, **_):
    """Worker 不动 git。后续可加 ArtifactStore checkpoint。"""
    return None


factorio_worker_publication.__publication_strategy__ = "skip"


@role(name="worker", description="Factorio in-game worker", role_type="worker", max_cost=1.0)
def worker(**params):
    return JobSpec(
        preparation_fn=factorio_worker_preparation,
        context_fn=context_spec(
            system_prompt_path="teams/factorio/prompts/worker.md",
            sections=[
                {"kind": "static", "content": "你只能通过 factorio_call_script 调用已注册脚本。"},
                {"kind": "dynamic", "section_type": "factorio_scripts"},
            ],
        ),
        publication_fn=factorio_worker_publication,
        tools=["factorio_call_script"],
    )
```

注意 `runtime_context.resources["evo_root"]` 这个值的来源 —— 需要 palimpsest runner 在创建 RuntimeContext 时把 evo path 写入 resources，或者 preparation_fn 通过 `evo_root` 注入参数（`tools.py:67` 显示 `evo_root` 已经是 injected_args 之一）。优先用注入参数：

```python
def factorio_worker_preparation(*, runtime_context, evo_root, **params):
    ...
    scripts_dir = Path(evo_root) / "teams" / "factorio" / "scripts"
```

**Step 4: prompts/worker.md**

写一个简短的 system prompt，说明 worker 的工作方式：goal → 用 `factorio_call_script` 调脚本 → 看返回 → 决定下一步 → 完成时停止。强调"如果你发现要调同一个脚本很多次，照样做完，事后会有 reviewer 评估是否值得抽象。"

**Verification:**

只能等 Task 9 的端到端 smoke。这一步只做语法/导入检查：
```bash
cd factorio-agent && python -c "from teams.factorio.roles.worker import worker; print(worker())"
```

---

## Task 7: 实现 implementer role + api_search tool + 写权限白名单

**Repo:** `/home/holo/factorio-agent`

**Files:**
- `teams/factorio/roles/implementer.py`
- `teams/factorio/tools/api_search.py`
- `teams/factorio/prompts/implementer.md`

**Step 1: api_search tool（包装 factorio-agent/agent/api_docs.py）**

不动 `agent/api_docs.py`（它已经能用），写一个薄 tool：

```python
from palimpsest.runtime.tools import tool, ToolResult
from agent.api_docs import ApiDocsIndex  # legacy path 仍然可用

_INDEX = None
def _idx():
    global _INDEX
    if _INDEX is None:
        _INDEX = ApiDocsIndex.load_default()  # files/runtime-api.json
    return _INDEX

@tool
def api_search(query: str) -> ToolResult:
    """Search Factorio Lua API for classes/methods matching the query."""
    hits = _idx().search(query)
    return ToolResult(success=True, output="\n".join(hits[:30]))

@tool
def api_detail(name: str) -> ToolResult:
    """Get full signature/description for a specific API name."""
    detail = _idx().detail(name)
    return ToolResult(success=True, output=detail or f"not found: {name}")
```

**Step 2: implementer role**

```python
from palimpsest.runtime.roles import role, JobSpec, context_spec, workspace_config


def implementer_publication(*, workspace_path, **_):
    """白名单：implementer 任务只允许写 teams/factorio/scripts/ 下的文件。
    在 commit 前扫描 staged diff，发现越界路径直接 raise。"""
    import subprocess
    result = subprocess.run(
        ["git", "-C", workspace_path, "diff", "--cached", "--name-only"],
        capture_output=True, text=True, check=True,
    )
    changed = [p.strip() for p in result.stdout.splitlines() if p.strip()]
    forbidden = [p for p in changed if not p.startswith("teams/factorio/scripts/") and not p.startswith("mod/scripts/")]
    if forbidden:
        raise ValueError(f"implementer wrote outside allowlist: {forbidden}")

    # 正常 commit + push 分支（沿用 git_publication 的标准实现）
    from palimpsest.stages.publication import git_publication
    return git_publication(workspace_path=workspace_path)


@role(name="implementer", description="Factorio Lua script implementer", role_type="worker", max_cost=2.0)
def implementer(**params):
    return JobSpec(
        preparation_fn=workspace_config(
            repo="https://github.com/<owner>/factorio-agent",  # 部署时填实际 URL
            init_branch="master",
            new_branch=True,
        ),
        context_fn=context_spec(
            system_prompt_path="teams/factorio/prompts/implementer.md",
            sections=[
                {"kind": "static", "content": "你的工作目录是 factorio-agent 仓库。只允许在 teams/factorio/scripts/ 下创建/修改 .lua 文件。"},
                {"kind": "dynamic", "section_type": "factorio_scripts"},  # 复用同一 catalog
            ],
        ),
        publication_fn=implementer_publication,
        tools=["bash", "read_file", "write_file", "api_search", "api_detail"],
    )
```

注意：`team` 字段不在这里设置，由 trigger 决定（implementer 任务从 ReviewProposal 派生时，task_template.team 默认 `default`）。

**Step 3: prompts/implementer.md**

提示词大意："你收到一个目标，要求在 factorio Lua 脚本目录新增/修改一个 action 脚本。现有脚本目录见 system prompt。可以用 api_search/api_detail 查 Factorio Lua API。写完后用 git add + 描述性 commit message。**只允许动 teams/factorio/scripts/ 下的文件**。"

**Verification:**
```bash
cd factorio-agent && python -c "from teams.factorio.roles.implementer import implementer; print(implementer())"
```

---

## Task 8: reviewer prompt 增加 factorio 演化知识 + driving task 准备

**Files:**
- `teams/factorio/prompts/reviewer-addendum.md`（新建，由全局 reviewer prompt include）
- 全局 reviewer role（位置待确认 —— 应在 evo/roles/reviewer.py 或 fixture）需要追加一段 instruction 引用上面的 addendum
- `teams/factorio/tasks/smoke-grid-place.yaml`（driving task 定义）

**Step 1: addendum 内容要点**

reviewer 在判断 `observation.tool_repetition` 时需要的额外知识：

> 如果 evidence 包含 `observation.tool_repetition` 且 `team == "factorio"`，且 `tool_name` 形如 `atomic.*`：
> - 这表示 worker 反复调用了一个底层原子操作，存在抽象成 action 脚本的机会
> - 应输出 ReviewProposal，`action_type=improve_tool`，`task_template.role="implementer"`，`task_template.team="default"`
> - `task_template.goal` 写明：在 `teams/factorio/scripts/actions/` 下创建一个新脚本封装该模式，脚本名根据 `arg_pattern` 命名
> - `evidence_events` 必须引用对应的 observation event_type / job_id / task_id

**Step 2: driving smoke task**

`teams/factorio/tasks/smoke-grid-place.yaml`：

```yaml
tasks:
  - team: factorio
    role: worker
    budget: 1.0
    goal: |
      在 (0,0) 到 (4,1) 范围内放置 10 个 iron-chest，组成 5x2 网格。
      使用现有 atomic 脚本完成。
```

第一次执行预期 worker 调 `atomic.place` 10 次 → 触发 `observation.tool_repetition` → reviewer → implementer 产出 `actions/place_grid.lua` → 第二次执行同样 task 预期 worker 调 `actions.place_grid` 1 次。

**Verification:**
```bash
yoitsu submit teams/factorio/tasks/smoke-grid-place.yaml --dry-run
# 验证 yaml 解析无报错、team/role 有效
```

---

## Task 9: 端到端 smoke

**Pre-requisites:**
- factorio headless server 已启动（用 factorio-agent 现有 systemd / 手动）
- RCON 凭据写入 `.env`
- yoitsu trenni / pasloe / palimpsest 容器已 build 并能通过 quadlet 启动
- factorio-agent 仓库已 clone 到 host 某路径，trenni job 容器通过 volume mount 把它挂成 evo

**Step 1: 启动 yoitsu 栈**

```bash
cd yoitsu
./deploy/quadlet/bin/up
```

**Step 2: 提交第一次 driving task**

```bash
yoitsu submit /path/to/factorio-agent/teams/factorio/tasks/smoke-grid-place.yaml
```

观察事件流，断言：
- worker job 完成，`observation.tool_repetition` 至少 1 个事件
- reviewer job 自动启动（由 observation_threshold 触发）
- reviewer job 输出 ReviewProposal JSON
- supervisor 解析成功，spawn 一个 implementer task
- implementer job 在 factorio-agent 上创建分支，提交一个新 `teams/factorio/scripts/actions/*.lua` 文件
- implementer publication path allowlist 通过

**Step 3: merge implementer 分支到 master**

MVP 阶段人工 merge（CI auto-merge 留给下一阶段）：

```bash
cd /path/to/factorio-agent
git fetch
git checkout master
git merge --ff-only <implementer-branch>
```

**Step 4: 提交第二次 driving task**

```bash
yoitsu submit /path/to/factorio-agent/teams/factorio/tasks/smoke-grid-place.yaml
```

断言：
- worker job 完成
- 该 job 的 `factorio_call_script` 调用次数显著低于第一次（理想情况：1 次 actions.place_grid，最差不超过 3 次）
- 不再产生 `observation.tool_repetition` 事件（或 call_count 远低于 min_count）

**Step 5: 记录证据**

把两次 job 的事件 dump（pasloe query）保存到 `docs/plans/2026-04-06-factorio-tool-evolution-mvp-results.md`，作为完成证据。

**完成标志：**

- yoitsu 在不依赖人类编写 Lua 的情况下，从一次任务执行的 observation 信号出发，**自主产出**了一个 commit 到 evo 仓库的新 Lua 脚本，且第二次执行同一任务时该脚本被自动使用。
- 整条链路涉及的非 evo 改动只有：yoitsu-contracts 加 2 个事件模型 / palimpsest 加 tool_pattern 检测和 emit / contexts loader 支持 team 子目录 / evo_root 可配置。所有其他逻辑都在 factorio-agent 仓库的 `teams/factorio/` 内。

---

## 风险与未决问题

1. **RCON 输出截断**：worker 的 dispatcher tool 已经返回 `truncated=True` 提示，但 reviewer 无法直接看到这个 meta。如果第一次 smoke 出现因截断导致 worker 卡住，需要在 Task 6 加一个 `truncated` 字段进 ToolResult 主体。
2. **observation_threshold 触发条件**：当前 reviewer 是按事件计数触发的，1 个 `tool_repetition` 事件可能不足以越过阈值。Task 9 跑前要确认 trenni 的 observation aggregation 配置允许"任何 observation.* 事件 ≥ 1 即触发"。如果不行，临时调阈值。
3. **implementer 写出的 Lua 不能跑**：implementer 是 LLM，可能写出语法错或运行时错的脚本。MVP 阶段不做静态检查；如果第二次 smoke 失败，看作正常的迭代信号，进入第二轮。
4. **factorio-agent 仓库的 git 历史会被 implementer 持续污染**：所有 implementer 分支都会进 master。MVP 接受这个，后续可以加 PR 中间环节。
5. **evo path 在容器内的 mount 策略**：本计划假设 trenni 启动 palimpsest job 容器时通过 volume 把 host 上的 factorio-agent clone 挂进容器。Task 4 修改了 env，但 quadlet volume 配置没改 —— Task 9 跑前要手工或加一个 trenni team config 配置项。
