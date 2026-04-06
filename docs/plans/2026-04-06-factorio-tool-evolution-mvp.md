# Factorio Tool Evolution MVP Implementation Plan

**Goal:** yoitsu 自主演化出一个 Factorio Lua 脚本。第一次 task 重复调用 actions.place → observation.tool_repetition 信号 → optimizer 提议新增封装脚本 → implementer 写出并 commit → 第二次 task 自动使用新脚本，调用次数显著下降。

**Architecture:**
- factorio-agent 仓库本身充当 evo（workaround，Phase 2 再做 multi-bundle）
- 共享 host 上的 factorio headless server，preparation_fn 通过 RCON 批量加载 evo 脚本
- worker（team=factorio，串行锁）暴露 1 个 dispatcher tool `factorio_call_script`
- implementer（team=default，可并发）写 Lua 文件，路径白名单限定到 teams/factorio/scripts/
- 新增 2 个 observation 信号（tool_repetition / context_late_lookup），保持独立模型
- 新增 trenni 定时聚合器，查 pasloe observation 事件，达阈值 spawn optimizer

**Tech Stack:** Python, Pydantic, factorio-rcon, yoitsu-contracts, palimpsest, trenni, Lua

**Non-goals:**
- 不做 multi-bundle evo overlay（留 Phase 2）
- 不做每 job 独立 factorio 实例（共享 host 实例）
- 不做 ArtifactStore checkpoint（留 Phase 3）

---

## Task 0: 实现 observation 聚合层（trenni 定时查询 + 本地聚合）

**Files:**
- Modify: `trenni/trenni/supervisor.py`
- Modify: `trenni/trenni/config.py`
- Add: `trenni/trenni/observation_aggregator.py`
- Modify: `trenni/tests/test_observation_aggregator.py`

**Step 1: 在 TrenniConfig 加聚合器配置**

```python
# trenni/config.py
@dataclass
class TrenniConfig:
    ...
    observation_aggregation_interval: float = 300.0  # 5 分钟
    observation_window_hours: int = 24
    observation_thresholds: dict[str, float] = field(default_factory=lambda: {
        "budget_variance": 0.3,
        "preparation_failure": 0.1,
        "tool_retry": 0.2,
        "tool_repetition": 5.0,  # 绝对计数，不是比率
        "context_late_lookup": 3.0,
    })
```

**Step 2: 实现聚合器模块**

```python
# trenni/observation_aggregator.py
"""Observation event aggregator for autonomous optimization loop.

Periodically queries pasloe for observation.* events, aggregates by metric_type,
and spawns optimizer tasks when thresholds are exceeded.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
import httpx
from loguru import logger


@dataclass
class AggregationResult:
    metric_type: str
    count: int
    threshold: float
    exceeded: bool
    role: str | None = None


async def aggregate_observations(
    pasloe_url: str,
    window_hours: int,
    thresholds: dict[str, float],
) -> list[AggregationResult]:
    """Query pasloe for observation.* events in window, aggregate by metric_type.
    
    Pasloe API: GET /events?since=<cutoff>&limit=1000&order=asc
    - No event_type_prefix filter, must fetch all and filter locally
    - Returns {"id", "source_id", "type", "ts", "data"}
    - Max limit=1000, need pagination via X-Next-Cursor
    """
    cutoff = datetime.utcnow() - timedelta(hours=window_hours)
    all_events = []
    cursor = None
    
    async with httpx.AsyncClient() as client:
        while True:
            params = {"since": cutoff.isoformat(), "limit": 1000, "order": "asc"}
            if cursor:
                params["cursor"] = cursor
            
            resp = await client.get(f"{pasloe_url}/events", params=params)
            resp.raise_for_status()
            batch = resp.json()
            
            # Filter observation.* events locally
            all_events.extend([e for e in batch if e.get("type", "").startswith("observation.")])
            
            cursor = resp.headers.get("X-Next-Cursor")
            if not cursor or len(batch) < 1000:
                break
    
    # Group by metric_type (从 type 提取，如 observation.tool_repetition → tool_repetition)
    counts: dict[str, int] = {}
    for evt in all_events:
        event_type = evt.get("type", "")
        if not event_type.startswith("observation."):
            continue
        metric = event_type.split(".", 1)[1] if "." in event_type else ""
        counts[metric] = counts.get(metric, 0) + 1
    
    results = []
    for metric, count in counts.items():
        threshold = thresholds.get(metric, float("inf"))
        results.append(AggregationResult(
            metric_type=metric,
            count=count,
            threshold=threshold,
            exceeded=(count >= threshold),
        ))
    
    return results
```

**Step 3: 在 supervisor 主循环加定时触发**

```python
# supervisor.py
class Supervisor:
    def __init__(self, config: TrenniConfig):
        ...
        self._last_aggregation = 0.0
    
    async def run(self):
        while True:
            ...
            # 定时聚合 observation
            now = time.time()
            if now - self._last_aggregation >= self.config.observation_aggregation_interval:
                await self._aggregate_and_spawn_optimizer()
                self._last_aggregation = now
            
            await asyncio.sleep(self.config.poll_interval)
    
    async def _aggregate_and_spawn_optimizer(self):
        from trenni.observation_aggregator import aggregate_observations
        from yoitsu_contracts.events import TriggerData
        
        results = await aggregate_observations(
            self.config.pasloe_url,
            self.config.observation_window_hours,
            self.config.observation_thresholds,
        )
        for r in results:
            if r.exceeded:
                logger.info(f"Observation threshold exceeded: {r.metric_type} ({r.count} >= {r.threshold})")
                # 构造 TriggerData 并调用 _process_trigger
                trigger_data = TriggerData(
                    trigger_type="observation_threshold",
                    goal=f"Analyze {r.metric_type} pattern ({r.count} occurrences in {self.config.observation_window_hours}h)",
                    role="optimizer",
                    team="default",
                    budget=0.5,
                    params={
                        "metric_type": r.metric_type,
                        "observation_count": r.count,
                        "window_hours": self.config.observation_window_hours,
                    },
                )
                # 创建 synthetic event
                from types import SimpleNamespace
                synthetic_event = SimpleNamespace(
                    id=f"obs-agg-{r.metric_type}-{int(time.time())}",
                    source_id="observation_aggregator",
                    type="trigger",
                    ts=datetime.utcnow().isoformat(),
                    data={},
                )
                await self._process_trigger(synthetic_event, trigger_data, replay=False)
```

**Step 4: 单元测试**

```python
# tests/test_observation_aggregator.py
import pytest
from trenni.observation_aggregator import aggregate_observations

@pytest.mark.asyncio
async def test_aggregate_below_threshold(mock_pasloe_server):
    # mock_pasloe_server 返回 3 个 observation.tool_repetition 事件
    results = await aggregate_observations(
        mock_pasloe_server.url, window_hours=24, thresholds={"tool_repetition": 5.0}
    )
    assert len(results) == 1
    assert results[0].metric_type == "tool_repetition"
    assert results[0].count == 3
    assert not results[0].exceeded

@pytest.mark.asyncio
async def test_aggregate_exceeds_threshold(mock_pasloe_server):
    # 返回 6 个事件
    results = await aggregate_observations(
        mock_pasloe_server.url, window_hours=24, thresholds={"tool_repetition": 5.0}
    )
    assert results[0].exceeded
```

**Verification:**
```bash
cd trenni && uv run pytest tests/test_observation_aggregator.py -v
```

---

## Task 1: 扩展 observation 信号合约（新增 2 个独立模型）

**Files:**
- Modify: `yoitsu-contracts/src/yoitsu_contracts/observation.py`
- Modify: `yoitsu-contracts/tests/test_observation_events.py`

**Step 1: 添加常量和模型**

```python
# observation.py
OBSERVATION_TOOL_REPETITION = "observation.tool_repetition"
OBSERVATION_CONTEXT_LATE_LOOKUP = "observation.context_late_lookup"

class ToolRepetitionData(BaseModel):
    """Emitted when a tool was called many times with similar args in one job."""
    job_id: str
    task_id: str
    role: str
    team: str
    tool_name: str
    call_count: int
    arg_pattern: str  # 字符串摘要，如 "grid_5x2"
    similarity: float  # 0.0-1.0

class ContextLateLookupData(BaseModel):
    """Emitted when a job repeatedly queried data that could be in context."""
    job_id: str
    task_id: str
    role: str
    tool_name: str
    call_count: int
    query_kind: str  # 字符串摘要
```

**Step 2: 单元测试**

```python
# tests/test_observation_events.py
def test_tool_repetition_flat_fields():
    data = ToolRepetitionData(
        job_id="j1", task_id="t1", role="worker", team="factorio",
        tool_name="factorio_call_script", call_count=10,
        arg_pattern="grid_5x2", similarity=0.85,
    )
    assert data.call_count == 10
    # 验证所有字段都是 primitive（无嵌套 dict/list）
    for k, v in data.model_dump().items():
        assert not isinstance(v, (dict, list))
```

**Verification:**
```bash
cd yoitsu-contracts && uv run pytest tests/test_observation_events.py::test_tool_repetition_flat_fields -v
```

---

## Task 2: 在 interaction loop 出口扫描并 emit 新信号

**Files:**
- Add: `palimpsest/palimpsest/runtime/tool_pattern.py`
- Modify: `palimpsest/palimpsest/stages/interaction.py`
- Add: `palimpsest/tests/test_tool_pattern.py`

**Step 1: 实现检测纯函数**

```python
# runtime/tool_pattern.py
from dataclasses import dataclass
import json

@dataclass
class ToolCallRecord:
    name: str
    args_json: str

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
    """Find tools called >= min_count with high arg similarity.
    
    For dispatcher tools (like factorio_call_script), extracts nested script_name
    from args and groups by that instead of tool name.
    """
    # Group by (tool_name, script_name_if_dispatcher)
    groups: dict[tuple[str, str], list[dict]] = {}
    for rec in history:
        try:
            args = json.loads(rec.args_json)
        except:
            args = {}
        
        # 如果 args 有 "name" 字段（dispatcher 的 script_name），用它分组
        script_name = args.get("name", "")
        key = (rec.name, script_name) if script_name else (rec.name, "")
        groups.setdefault(key, []).append(args)
    
    findings = []
    for (tool_name, script_name), args_list in groups.items():
        if len(args_list) < min_count:
            continue
        
        # 计算参数结构相似度（key-set overlap）
        if not args_list:
            continue
        key_sets = [set(a.keys()) for a in args_list]
        avg_similarity = sum(
            len(k1 & k2) / max(len(k1 | k2), 1)
            for i, k1 in enumerate(key_sets)
            for k2 in key_sets[i+1:]
        ) / max(len(key_sets) * (len(key_sets) - 1) / 2, 1)
        
        if avg_similarity >= similarity_threshold:
            # arg_pattern: 如果是 dispatcher，用 script_name；否则用 tool_name
            pattern = script_name if script_name else tool_name
            findings.append(RepetitionFinding(
                tool_name=f"{tool_name}({script_name})" if script_name else tool_name,
                call_count=len(args_list),
                arg_pattern=pattern,
                similarity=avg_similarity,
            ))
    
    return findings
```

**Step 2: 在 interaction.py 出口调用**

```python
# stages/interaction.py
def run_interaction_loop(...):
    tool_call_history: list[ToolCallRecord] = []
    
    while not done:
        ...
        if tool_calls:
            for tc in tool_calls:
                result = execute_tool(tc.name, tc.args)
                tool_call_history.append(ToolCallRecord(
                    name=tc.name,
                    args_json=json.dumps(tc.args, sort_keys=True),
                ))
    
    # Loop 结束，扫描 pattern
    from palimpsest.runtime.tool_pattern import detect_repetition
    repetitions = detect_repetition(tool_call_history)
    for r in repetitions:
        gateway.emit_observation(
            event_type="observation.tool_repetition",
            data={
                "job_id": job_id,
                "task_id": task_id,
                "role": role_name,
                "team": team,
                "tool_name": r.tool_name,
                "call_count": r.call_count,
                "arg_pattern": r.arg_pattern,
                "similarity": r.similarity,
            },
        )
```

**Step 3: 单元测试**

```python
# tests/test_tool_pattern.py
def test_detect_repetition_dispatcher_groups_by_script_name():
    history = [
        ToolCallRecord("factorio_call_script", '{"name": "actions.place", "x": 0, "y": 0}'),
        ToolCallRecord("factorio_call_script", '{"name": "actions.place", "x": 1, "y": 0}'),
        ToolCallRecord("factorio_call_script", '{"name": "actions.place", "x": 2, "y": 0}'),
        ToolCallRecord("factorio_call_script", '{"name": "actions.place", "x": 3, "y": 0}'),
        ToolCallRecord("factorio_call_script", '{"name": "actions.place", "x": 4, "y": 0}'),
    ]
    findings = detect_repetition(history, min_count=5, similarity_threshold=0.7)
    assert len(findings) == 1
    assert findings[0].tool_name == "factorio_call_script(actions.place)"
    assert findings[0].call_count == 5
    assert findings[0].arg_pattern == "actions.place"
```

**Verification:**
```bash
cd palimpsest && uv run pytest tests/test_tool_pattern.py -v
```

---

## Task 3: 让 context provider loader 支持 team 子目录

**Files:**
- Modify: `palimpsest/palimpsest/runtime/contexts.py:48-75`
- Modify: `palimpsest/tests/test_context_loader.py`

**Step 1: 修改 resolve_context_functions 签名**

```python
# contexts.py:48
def resolve_context_functions(
    evo_root: str | Path,
    requested: list[str],
    team: str = "default",  # 新增参数
) -> dict[str, Callable]:
    """Scan evo/teams/<team>/contexts/ first, then evo/contexts/ for fallback."""
```

**Step 2: 实现 team-first 扫描**

```python
# contexts.py:51-75
    requested_set = set(requested)
    result: dict[str, Callable] = {}
    
    # Scan team-specific first (higher priority)
    team_dir = Path(evo_root) / "teams" / team / "contexts"
    global_dir = Path(evo_root) / "contexts"
    
    for scan_dir in (team_dir, global_dir):
        if not scan_dir.is_dir():
            continue
        for py_file in sorted(scan_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            funcs = _load_context_functions(py_file)
            for section_type, func in funcs.items():
                if section_type in requested_set and section_type not in result:
                    result[section_type] = func
    
    missing = requested_set - set(result.keys())
    if missing:
        logger.warning(f"Context providers not found: {missing}")
    
    return result
```

**Step 3: 调用方传入 team**

在 `palimpsest/stages/context.py:44` 调用时传入 team：
```python
# context.py:44
if evo_root:
    registry = resolve_context_functions(evo_root, section_types, team=job_config.team)
```

**Step 4: 单元测试**

```python
# tests/test_context_loader.py
def test_team_context_overrides_global(tmp_path):
    # 创建 global context
    (tmp_path / "contexts").mkdir()
    (tmp_path / "contexts" / "test.py").write_text('''
from palimpsest.runtime.contexts import context_provider
@context_provider("foo")
def foo(**_): return "global"
''')
    # 创建 team context
    (tmp_path / "teams" / "factorio" / "contexts").mkdir(parents=True)
    (tmp_path / "teams" / "factorio" / "contexts" / "test.py").write_text('''
from palimpsest.runtime.contexts import context_provider
@context_provider("foo")
def foo(**_): return "team"
''')
    
    result = resolve_context_functions(tmp_path, ["foo"], team="factorio")
    assert result["foo"]() == "team"  # team 版本优先
```

**Verification:**
```bash
cd palimpsest && uv run pytest tests/test_context_loader.py::test_team_context_overrides_global -v
```

---

## Task 4: 让 preparation_fn 支持 evo_root 注入

**Files:**
- Modify: `palimpsest/palimpsest/runner.py:138-141`

**Step 1: 在 prep_params 注入 evo_root**

```python
# runner.py:138-141
        prep_sig = inspect.signature(spec.preparation_fn)
        if "runtime_context" in prep_sig.parameters:
            prep_params["runtime_context"] = runtime_context
        if "evo_root" in prep_sig.parameters:
            prep_params["evo_root"] = str(evo_path)
        workspace_cfg = spec.preparation_fn(**prep_params)
```

**Verification:**
手工验证（Task 6 的 worker preparation_fn 会依赖这个注入）：
```python
def test_prep_fn(*, evo_root, **_):
    print(f"evo_root={evo_root}")
    return WorkspaceConfig(repo="", new_branch=False)
```

---

## Task 5: 重组 factorio-agent 仓库为 evo 结构

**Repo:** `/home/holo/factorio-agent`

**Step 1: 创建顶层 evo 目录**

```bash
cd /home/holo/factorio-agent
mkdir -p roles tools contexts
touch roles/.gitkeep tools/.gitkeep contexts/.gitkeep
```

**Step 2: 移动 RCON/bridge 到 teams/factorio/lib/**

```bash
mkdir -p teams/factorio/lib
git mv agent/rcon.py teams/factorio/lib/rcon.py
git mv agent/bridge.py teams/factorio/lib/bridge.py
```

更新 `agent/run.py` 等文件的 import：
```python
# 旧：from agent.rcon import RCONClient
# 新：from teams.factorio.lib.rcon import RCONClient
```

**Step 3: scripts/ 目录 symlink**

```bash
mkdir -p teams/factorio
ln -s ../../mod/scripts teams/factorio/scripts
```

**Step 4: 创建空的 role/tool/context 目录**

```bash
mkdir -p teams/factorio/{roles,tools,contexts,prompts}
touch teams/factorio/{roles,tools,contexts,prompts}/.gitkeep
```

**Step 5: commit**

```bash
git add teams/ roles/ tools/ contexts/ agent/
git commit -m "restructure: adopt yoitsu evo layout (MVP workaround)

- Add top-level roles/tools/contexts/ (empty, for evo compatibility)
- Move agent/rcon.py → teams/factorio/lib/rcon.py
- Move agent/bridge.py → teams/factorio/lib/bridge.py
- Symlink teams/factorio/scripts → mod/scripts
- Create teams/factorio/{roles,tools,contexts,prompts}/ structure

This repo now serves as evo_root for yoitsu factorio team.
Multi-bundle overlay deferred to Phase 2."
```

**Verification:**
```bash
test -L teams/factorio/scripts && echo "symlink ok"
test -f teams/factorio/lib/rcon.py && echo "rcon moved"
python -c "import sys; sys.path.insert(0, '.'); from teams.factorio.lib.rcon import RCONClient; print('import ok')"
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
# teams/factorio/tools/factorio_call_script.py
"""Dispatcher tool for calling Factorio mod scripts via RCON."""
from palimpsest.runtime.tools import tool, ToolResult
from palimpsest.runtime.context import RuntimeContext


@tool
def factorio_call_script(
    name: str,
    args: str = "",
    runtime_context: RuntimeContext = None,
) -> ToolResult:
    """Call a Factorio mod script via RCON.
    
    Args:
        name: script name (e.g. 'actions.place', 'atomic.teleport')
        args: argument string (typically JSON)
    """
    if runtime_context is None or "rcon" not in runtime_context.resources:
        return ToolResult(success=False, output="No RCON connection")
    
    rcon = runtime_context.resources["rcon"]
    command = f"/agent {name} {args}".strip()
    raw = rcon.send_command(command)
    
    # RCON 单包 ~4KB 限制，截断时前缀标记
    if len(raw.encode("utf-8")) >= 4000:
        raw = "[TRUNCATED 4KB]\n" + raw[:3900]
    
    return ToolResult(success=True, output=raw)
```

**Step 2: factorio_scripts context provider**

```python
# teams/factorio/contexts/factorio_scripts.py
"""Inject Factorio script catalog into system prompt."""
from pathlib import Path
import re
from palimpsest.runtime.contexts import context_provider


@context_provider("factorio_scripts")
def factorio_scripts(*, evo_root, **_):
    """Scan teams/factorio/scripts/ and return catalog as markdown list."""
    scripts_dir = Path(evo_root) / "teams" / "factorio" / "scripts"
    if not scripts_dir.exists():
        return "No scripts found."
    
    catalog = []
    for lua_path in sorted(scripts_dir.rglob("*.lua")):
        rel = lua_path.relative_to(scripts_dir).with_suffix("")
        name = str(rel).replace("/", ".")
        # 提取首行注释作为描述
        lines = lua_path.read_text(encoding="utf-8").splitlines()
        desc = ""
        if lines and (m := re.match(r"--\s*(.+)", lines[0])):
            desc = m.group(1).strip()
        catalog.append(f"- `{name}` — {desc}" if desc else f"- `{name}`")
    
    return "\n".join(catalog) if catalog else "No scripts available."
```

**Step 3: worker role**

```python
# teams/factorio/roles/worker.py
"""Factorio worker role: connects RCON, loads scripts, executes in-game tasks."""
from palimpsest.runtime.roles import role, JobSpec, context_spec
from palimpsest.config import WorkspaceConfig
from teams.factorio.lib.rcon import RCONClient
import os


def factorio_worker_preparation(*, runtime_context, evo_root, **params):
    """Connect RCON. Do NOT batch-load existing scripts (they use require, incompatible with dynamic loader).
    
    Only new scripts written by implementer (which follow dynamic script constraints) will be registered.
    Existing actions.place etc. are pre-loaded by mod at startup via require().
    """
    from pathlib import Path
    
    # Connect RCON
    rcon = RCONClient(
        host=os.environ.get("FACTORIO_RCON_HOST", "localhost"),
        port=int(os.environ.get("FACTORIO_RCON_PORT", "27015")),
        password=os.environ.get("FACTORIO_RCON_PASSWORD", "changeme"),
    )
    rcon.connect()
    runtime_context.resources["rcon"] = rcon
    runtime_context.register_cleanup(rcon.close)
    
    # 可选：只 register 新增的动态脚本（如 actions/place_grid.lua）
    # 判断方式：脚本首行有 "-- DYNAMIC" 标记，或放在 teams/factorio/scripts/dynamic/ 子目录
    # MVP 阶段先不做自动 register，让 implementer 产出的脚本在第二次 job 时手工 register
    # 或者在 context_fn 里通过 RCON list_scripts 获取当前可用脚本列表
    
    # Worker 不需要 git workspace
    return WorkspaceConfig(repo="", new_branch=False)


def factorio_worker_publication(*, **_):
    """Worker 不产出 git commit，后续可加 ArtifactStore checkpoint。"""
    return None


factorio_worker_publication.__publication_strategy__ = "skip"


@role(
    name="worker",
    description="Factorio in-game worker with RCON",
    role_type="worker",
    max_cost=1.0,
)
def worker(**params):
    return JobSpec(
        preparation_fn=factorio_worker_preparation,
        context_fn=context_spec(
            system="teams/factorio/prompts/worker.md",
            sections=[{"type": "factorio_scripts"}],
        ),
        publication_fn=factorio_worker_publication,
        tools=["factorio_call_script"],
    )
```

**Step 4: prompts/worker.md**

```markdown
# Factorio Worker

你是一个在 Factorio 游戏中执行任务的 agent。你只能通过 `factorio_call_script` 工具调用已注册的脚本。

## 可用脚本

下面是当前可用的脚本列表（由 context provider 动态注入）：

<!-- factorio_scripts section will be appended here by build_context -->

## 工作流程

1. 理解目标（goal）
2. 选择合适的脚本调用
3. 根据返回结果决定下一步
4. 完成目标后停止

## 注意事项

- 如果发现需要反复调用同一个脚本，照样完成任务。事后会有 optimizer 评估是否值得抽象。
- 如果脚本返回 `[TRUNCATED 4KB]`，说明输出过大，考虑分页或写文件。
```

注意：`{factorio_scripts}` 占位符不会被 build_context 替换。dynamic section 内容会追加到 system prompt 之后，作为独立段落。

**Verification:**
```bash
cd /home/holo/factorio-agent
python -c "from teams.factorio.roles.worker import worker; print(worker())"
```

---

## Task 7: 实现 implementer role + api_search tool

**Repo:** `/home/holo/factorio-agent`

**Files:**
- `teams/factorio/roles/implementer.py`
- `teams/factorio/tools/api_search.py`
- `teams/factorio/tools/api_detail.py`
- `teams/factorio/prompts/implementer.md`

**Step 1: api_search / api_detail tools**

```python
# teams/factorio/tools/api_search.py
from palimpsest.runtime.tools import tool, ToolResult
from agent.api_docs import ApiIndex

_INDEX = None
def _get_index():
    global _INDEX
    if _INDEX is None:
        _INDEX = ApiIndex()
        _INDEX.load()
    return _INDEX

@tool
def api_search(query: str) -> ToolResult:
    """Search Factorio Lua API for classes/methods matching query."""
    results = _get_index().search(query, limit=30)
    lines = [f"{r['name']} ({r['kind']}) — {r['summary']}" for r in results]
    return ToolResult(success=True, output="\n".join(lines) if lines else "No results")

@tool
def api_detail(name: str) -> ToolResult:
    """Get full details for a specific API entry."""
    detail = _get_index().detail(name)
    if not detail:
        return ToolResult(success=False, output=f"Not found: {name}")
    
    lines = [
        f"Name: {detail['name']}",
        f"Kind: {detail['kind']}",
        f"Description: {detail['description']}",
    ]
    if "type_info" in detail:
        lines.append(f"Type: {detail['type_info']}")
    return ToolResult(success=True, output="\n".join(lines))
```

**Step 2: implementer role**

```python
# teams/factorio/roles/implementer.py
"""Implementer role: writes Lua scripts in factorio-agent repo."""
import os
from palimpsest.runtime.roles import role, JobSpec, context_spec, workspace_config, git_publication


def implementer_publication(*, workspace_path, **kwargs):
    """Path allowlist: only allow writes to teams/factorio/scripts/."""
    import subprocess
    
    result = subprocess.run(
        ["git", "-C", workspace_path, "diff", "--cached", "--name-only"],
        capture_output=True, text=True, check=True,
    )
    changed = [p.strip() for p in result.stdout.splitlines() if p.strip()]
    forbidden = [
        p for p in changed
        if not p.startswith("teams/factorio/scripts/") and not p.startswith("mod/scripts/")
    ]
    if forbidden:
        raise ValueError(f"Implementer wrote outside allowlist: {forbidden}")
    
    # 调用 git_publication factory 返回的 callable
    pub_fn = git_publication(strategy="branch")
    return pub_fn(workspace_path=workspace_path, **kwargs)


@role(
    name="implementer",
    description="Factorio Lua script implementer",
    role_type="worker",
    max_cost=2.0,
)
def implementer(**params):
    return JobSpec(
        preparation_fn=workspace_config(
            repo=os.environ.get("FACTORIO_AGENT_REPO", "https://github.com/org/factorio-agent"),
            init_branch="master",
            new_branch=True,
        ),
        context_fn=context_spec(
            system="teams/factorio/prompts/implementer.md",
            sections=[{"type": "factorio_scripts"}],
        ),
        publication_fn=implementer_publication,
        tools=["bash"],  # 只用 bash，read_file/write_file 需要在 evo/tools/ 提供
    )
```

**Step 3: prompts/implementer.md**

```markdown
# Factorio Implementer

你的任务是在 factorio-agent 仓库中编写或修改 Lua 脚本。

## 当前脚本目录

下面是当前可用的脚本列表（由 context provider 动态注入）：

<!-- factorio_scripts section will be appended here by build_context -->

## 工作流程

1. 理解目标（goal）—— 通常是"在 teams/factorio/scripts/actions/ 下新增一个封装脚本"
2. 用 `api_search` / `api_detail` 查阅 Factorio Lua API
3. 用 `bash` 的 `cat` 读取现有脚本作为参考
4. 用 `bash` 的 `cat > file <<'EOF'` 写新脚本到 `teams/factorio/scripts/actions/<name>.lua`
5. 用 `bash` 执行 `git add` 和 `git commit`

## 路径限制

**只允许写 `teams/factorio/scripts/` 下的文件**。写其他路径会被 publication 阶段拒绝。

## Lua 脚本格式（动态脚本约束）

新脚本必须符合动态脚本约束（不能使用 `require`）：

```lua
-- 首行注释：简短描述
-- DYNAMIC (标记为动态脚本)
return function(args_str)
    -- args_str 是 JSON 字符串，用 game.json_to_table() 解析
    local args = game.json_to_table(args_str)
    
    -- 你的逻辑（不能 require 其他模块）
    
    -- 返回结果（serialize 已自动注入）
    return serialize({ok = true, result = ...})
end
```

注意：现有 actions.place 等脚本使用 `require`，不能作为动态脚本模板。新脚本必须自包含。
```

**Verification:**
```bash
cd /home/holo/factorio-agent
python -c "from teams.factorio.roles.implementer import implementer; print(implementer())"
```

---

## Task 8: optimizer prompt 增加 factorio 演化知识

**Files:**
- `teams/factorio/prompts/optimizer-addendum.md` (新建)
- 全局 optimizer role prompt 需要 include 这个 addendum（位置待确认）

**Step 1: addendum 内容**

```markdown
# Factorio Tool Evolution Guidance

当你分析 `observation.tool_repetition` 事件时，如果：
- `team == "factorio"`
- `tool_name` 包含 `factorio_call_script(actions.*)`
- `call_count >= 5`

这表示 worker 反复调用了同一个 action 脚本，存在抽象成更高层脚本的机会。

## 应输出的 ReviewProposal

```json
{
  "problem_classification": {
    "category": "tool_reliability",
    "severity": "medium",
    "summary": "Worker repeatedly called actions.place (10 times), pattern: grid_5x2"
  },
  "executable_proposal": {
    "action_type": "improve_tool",
    "description": "Create actions/place_grid.lua to encapsulate grid placement pattern",
    "estimated_impact": "Reduce tool calls from 10 to 1 for grid placement tasks"
  },
  "task_template": {
    "goal": "在 teams/factorio/scripts/actions/ 下创建 place_grid.lua，封装网格放置模式（参考 arg_pattern: grid_5x2）",
    "role": "implementer",
    "team": "default",
    "budget": 1.5
  }
}
```

## 关键点

- `task_template.role` 必须是 `"implementer"`（不是 worker）
- `task_template.team` 是 `"default"`（implementer 不占用 factorio 串行锁）
- `goal` 要明确指定文件路径和参考的 arg_pattern
```

**Step 2: 全局 optimizer prompt include**

（这一步需要先找到全局 optimizer role 的 prompt 文件位置，MVP 阶段可以手工把 addendum 内容直接追加到 optimizer prompt 末尾）

**Verification:**
手工验证（Task 9 端到端 smoke 时观察 optimizer 输出）

---

## Task 9: 端到端 smoke

**Pre-requisites:**
- factorio headless server 已启动（host 上，RCON 端口 27015）
- yoitsu trenni / pasloe / palimpsest 容器已 build
- factorio-agent 仓库已 clone 到 host，路径配置到 trenni 的 `PALIMPSEST_EVO_DIR`
- trenni config 中 factorio team 配置：
  ```yaml
  teams:
    factorio:
      runtime:
        env_allowlist: [FACTORIO_RCON_HOST, FACTORIO_RCON_PORT, FACTORIO_RCON_PASSWORD, PALIMPSEST_EVO_DIR]
      scheduling:
        max_concurrent_jobs: 1
  ```

**Step 1: 启动 yoitsu 栈**

```bash
cd /home/holo/yoitsu
# 假设有 deploy/quadlet 启动脚本，或手工 podman run
systemctl --user start yoitsu-pasloe yoitsu-trenni
```

**Step 2: 提交第一次 driving task**

```bash
cat > /tmp/factorio-grid-task.yaml <<EOF
tasks:
  - team: factorio
    role: worker
    budget: 1.0
    goal: |
      在 (0,0) 到 (4,1) 范围内放置 10 个 iron-chest，组成 5x2 网格。
      使用现有脚本完成。
EOF

yoitsu submit /tmp/factorio-grid-task.yaml
```

**Step 3: 观察事件流**

等待 5-10 分钟，观察：
- worker job 完成
- pasloe 收到至少 1 个 `observation.tool_repetition` 事件（tool_name 包含 `actions.place`）
- trenni 聚合器触发，spawn optimizer job
- optimizer job 输出 ReviewProposal JSON
- supervisor 解析成功，spawn implementer task
- implementer job 创建分支，写 `teams/factorio/scripts/actions/place_grid.lua`，commit

**Step 4: merge implementer 分支**

```bash
cd /home/holo/factorio-agent
git fetch
git checkout master
git merge --ff-only <implementer-branch>
```

**Step 5: 提交第二次 driving task**

```bash
yoitsu submit /tmp/factorio-grid-task.yaml
```

断言：
- worker job 完成
- 该 job 的 `factorio_call_script` 调用次数显著低于第一次（理想：1 次 `actions.place_grid`）
- 不再产生 `observation.tool_repetition` 事件（或 call_count < 5）

**Step 6: 记录证据**

```bash
# 查询两次 job 的 tool call 历史（通过 pasloe HTTP API 或 trenni logs）
curl "http://localhost:8000/events?type=tool.exec&limit=1000" | jq '.[] | select(.data.job_id == "<job1>")'
curl "http://localhost:8000/events?type=tool.exec&limit=1000" | jq '.[] | select(.data.job_id == "<job2>")'

# 保存到文档
cat > docs/plans/2026-04-06-factorio-tool-evolution-mvp-results.md <<EOF
# Factorio Tool Evolution MVP Results

## First Run
- Job ID: <job1>
- Tool calls: 10x factorio_call_script(actions.place)
- observation.tool_repetition emitted: yes

## Optimizer Output
- ReviewProposal: <paste JSON>
- Implementer branch: <branch-name>
- New script: teams/factorio/scripts/actions/place_grid.lua

## Second Run
- Job ID: <job2>
- Tool calls: 1x factorio_call_script(actions.place_grid)
- observation.tool_repetition emitted: no

## Conclusion
演化成功：yoitsu 自主产出了一个新 Lua 脚本，第二次执行同一任务时工具调用次数从 10 降到 1。
EOF
```

**完成标志：**
- yoitsu 在无人工编写 Lua 的情况下，从 observation 信号出发，自主产出了一个 commit 到 evo 仓库的新脚本
- 第二次执行同一任务时该脚本被自动使用，工具调用次数显著下降
- 整条链路的非 evo 改动只有：yoitsu-contracts 加 2 个事件模型 / palimpsest 加 tool_pattern 检测 / contexts loader 支持 team / runner 注入 evo_root / trenni 加聚合器

---

## 风险与未决问题

1. **RCON register 协议的 `>>>` 转义**：如果 Lua 代码里有 `>>>` 字符串会破坏协议。MVP 假设不含；生产环境需要 base64 或换协议。
2. **observation 聚合器的阈值调优**：`tool_repetition: 5.0` 是拍脑袋的值，可能需要根据实际任务调整。
3. **implementer 写出的 Lua 语法错**：LLM 可能写出不能跑的脚本。MVP 不做静态检查，第二次 smoke 失败时进入第二轮迭代。
4. **factorio 服务器的网络可达性**：palimpsest job 容器需要能访问 host 上的 RCON 端口（27015）。如果容器网络隔离，需要配置 `--network=host` 或端口映射。
5. **evo_root 在容器内的 mount**：trenni 启动 palimpsest job 容器时需要把 host 上的 factorio-agent clone 挂进容器。这需要在 trenni 的 podman backend 配置 volume mount（当前 plan 未涉及，需要手工或加 config）。
6. **现有脚本的 require 依赖**：actions.place 等现有脚本使用 `require("scripts.lib.agent")`，不能通过 RCON register 动态加载。MVP 阶段只有新产出的脚本（符合动态脚本约束）才能热加载；现有脚本继续走 mod 预加载路径。
7. **implementer 工具集限制**：只有 bash 可用，需要用 `cat`/`cat >` 读写文件。如果需要 read_file/write_file，必须在 factorio-agent/tools/ 下提供这两个工具的实现。