# Factorio 优化闭环收尾计划 (v2)

> 2026-04-08 执行状态：Task 1-4 代码已完成；optimizer proposal task-id collision 已在 live Trenni 验证修复；Task 5 已恢复真实 smoke，但当前阻塞在 implementer 任务成功后产物未出现在 bundle/mod scripts 目录。

**Goal:** 把 Factorio 自演化闭环从"逻辑通"推到"实际产出领域优化"。可量化目标：跑一次"用挖矿机挖 50 铁矿"任务，第一轮 worker 因 `factorio_call_script(name="find_ore_basic", ...)` 反复探索花 ~12 步；现有 `tool_repetition` 检测自动触发 → optimizer 拿到丰富证据后产出 `improve_tool` 提议 → implementer 直接在 bundle 内写出新 lua → 第二轮 worker preparation 重载新脚本 → 同任务步数降到 1-2。

**Architecture:** 把 bundle 当作自演化的目标对象，而不是基础设施。三个轴的修正：
1. **Optimizer 是 factorio bundle 下的独立 role**，不再走 default + addendum 叠加；它的 prompt 完整、自洽，且在 spawn 时拿到 observation 的真实证据（tool_name、arg_pattern、call_count、bundle 等）。
2. **Implementer 的 workspace 直接是 evo_root**，通过新增的 `WorkspaceConfig.workspace_override` 字段实现；agent 在 bundle 内写文件，无 publication，写完即生效。
3. **Worker 的 preparation 重建运行环境**：把当前 bundle 的 `factorio/scripts/` 同步进 Factorio mod 目录并触发 `/reload`，再连 RCON。这样上一轮 implementer 的写入在下一轮 worker 启动时自动可用。

为这两件事铺一层 reusable preparation building blocks（`evo/factorio/lib/preparation.py`），role 自己的 `preparation_fn` 只是调用这些 building block 的薄壳。后续"role.preparation 改为 fn 列表"重构出现时，这层就是天然的零件库。

**关于 script_name 字段（重要的现状澄清）:** `RepetitionFinding` / `ObservationToolRepetitionEvent` **没有**独立的 `script_name` 字段。对 dispatcher tool（如 `factorio_call_script`），现有编码是：
- `tool_name = "factorio_call_script(find_ore_basic)"`（dispatcher 包了一层）
- `arg_pattern = "find_ore_basic"`（这个字段名"撒了谎"——对 dispatcher 它存的是 script name，不是 args 模式）
- `bundle` 字段已存在，可直接用于路由

本计划**不**改 contracts 添加 `script_name` 字段；而是让 optimizer prompt 和 supervisor 都按这个既有编码读取。在涉及证据透传和 prompt 设计的任务里都明确写出这条约定。

**Tech Stack:** Python (palimpsest, trenni), Lua, RCON, yoitsu-contracts。无新增依赖。

**Non-goals (本计划不做):**
- 不引入"role preparation = fn 列表"的组合机制（继续每 role 一个 preparation_fn，只是内部委托给 building blocks）
- 不新增 metric 类型（用现有 `observation.tool_repetition`，因为 `tool_pattern.py` 的分组键已经是 `(tool_name, script_name)`，对 iron ore 这种"同一脚本不同坐标"场景天然命中）
- 不引入独立 eval role（worker self-reflection 也不做；现有 pattern 检测够用）
- 不把 factorio mod 源码搬进 bundle（保持 mod scripts 通过 bind-mount 暴露给 server）
- 不强制 implementer 路径白名单（依赖 bundle 容器隔离 + factorio bundle 串行化配置；TODO 留在 Task 3 收尾）。**注意：当前 dev 部署 `deploy/quadlet/trenni.dev.yaml` 是 `max_workers: 1` 全局单 worker，等于天然串行；但 `config/trenni.yaml` 默认是 `max_workers: 4`，本计划要求显式给 factorio bundle 加 `bundles.factorio.scheduling.max_concurrent_jobs = 1`，避免任何环境下 implementer 并发改写 evo_root**
- 不动 ADR-0010/0014 文档（等 smoke 通过后再回头补）

**留作后续 (Phase 2+):**
- role.preparation_fn 改为 building block 列表组合
- 把 factorio mod 源码搬进 `evo/factorio/mod/`
- 引入 eval role + 真正的 trajectory reflection
- artifact-linked 优化目标
- 自定义 observation event types

---

## Task 1: Supervisor — optimizer 路由 + observation 证据透传

**目标:** 干掉 `bundle="default"` 硬编码（用 observation 事件本身的 `bundle` 字段路由）；把每个 evidence 事件的 `tool_name / arg_pattern / call_count / similarity / bundle` 拉出来塞进 optimizer spawn 的 `params.evidence`。**不**新增 `script_name` 字段——optimizer 按现有编码（`tool_name="factorio_call_script(<script>)"`, `arg_pattern="<script>"`）解析。

**Files:**
- Modify: `trenni/trenni/supervisor.py` (~1500-1540 区段，构造 optimizer trigger_data 的地方)
- Modify: `trenni/trenni/observation_aggregator.py`（让 aggregation result 携带 evidence event payload，而不仅是 count）
- Test: `trenni/tests/` 下相关 supervisor / aggregator 测试

**改动要点:**

A. 让 aggregator 的 result 类型除了 `count / threshold / metric_type / new_ids` 之外多带一个 `evidence: list[dict]` 字段。每个 dict 是从 `ObservationToolRepetitionEvent` 抽出的 payload：`{role, bundle, tool_name, call_count, arg_pattern, similarity}`。建议取最新 5 条。

B. 在 `supervisor.py` 构造 `trigger_data` 处：
```python
# 旧
trigger_data = {
    "goal": "...",
    "role": "optimizer",
    "bundle": "default",  # 删掉
    "budget": 0.5,
    "params": {
        "metric_type": r.metric_type,
        "observation_count": r.count,
        "window_hours": self.config.observation_window_hours,
    },
}

# 新
target_bundle = _resolve_bundle_for_observations(r.evidence)  # 见下
trigger_data = {
    "goal": f"Analyze {r.metric_type} pattern in bundle '{target_bundle}' "
            f"({r.count} occurrences in {self.config.observation_window_hours}h window). "
            "Output a ReviewProposal JSON in your summary.",
    "role": "optimizer",
    "bundle": target_bundle,
    "budget": 0.5,
    "params": {
        "metric_type": r.metric_type,
        "observation_count": r.count,
        "window_hours": self.config.observation_window_hours,
        "evidence": r.evidence,  # 透传给 optimizer，包含 tool_name + arg_pattern + bundle
    },
}
```

C. `_resolve_bundle_for_observations(evidence)`：`ObservationToolRepetitionEvent` 已经有 `bundle` 字段（见 `yoitsu-contracts/src/yoitsu_contracts/observation.py:91`），所以直接取众数即可：
```python
def _resolve_bundle_for_observations(evidence: list[dict]) -> str:
    from collections import Counter
    bundles = [e.get("bundle", "") for e in evidence if e.get("bundle")]
    if not bundles:
        logger.warning("Observation evidence missing bundle field; falling back to 'default'")
        return "default"
    return Counter(bundles).most_common(1)[0][0]
```

**Steps:**

- [ ] 1.1 在 aggregator 的 result 类型里加 `evidence: list[dict]` 字段；`aggregate()` 在拼装 result 时取最新 5 条相关 observation 事件的 payload。
- [ ] 1.2 改 `supervisor.py:1518` 那段：删掉 `bundle="default"`，用 `_resolve_bundle_for_observations(r.evidence)` 决定 bundle；把 `evidence` 加到 params。
- [ ] 1.3 实现 `_resolve_bundle_for_observations`（同文件，私有 helper），策略如上。
- [ ] 1.4 单测：mock 一个 aggregation result，evidence 里 5 条都标 bundle=factorio，断言 trigger_data.bundle == "factorio" 且 params.evidence 有 5 条且每条都含 tool_name + arg_pattern。
  ```bash
  cd trenni && pytest tests/ -k optimizer_spawn -v
  ```
- [ ] 1.5 单测：evidence 为空时 fallback 到 default 且 log warning。
- [ ] 1.6 跑 trenni 全量测试：
  ```bash
  cd trenni && pytest -q
  ```
- [ ] 1.7 commit：`feat(trenni): route optimizer spawn by observation bundle and pass evidence`

**完成标志:** 对一个标了 bundle=factorio 的合成 observation 事件触发聚合，spawn 出来的 optimizer trigger_data 里 bundle=factorio 且 params.evidence 非空。

---

## Task 2: Factorio-specific optimizer role

**目标:** `optimizer` 从一个跨 bundle 通用 role 变成 factorio bundle 下的独立 role。它的 prompt 完整自洽，知道 factorio_call_script 语义、知道 `factorio/scripts/` 布局、能从 `params.evidence` 读出具体 tool/script/arg_pattern，输出针对 `factorio/scripts/` 下新文件的 ReviewProposal。

**Files:**
- Create: `evo/factorio/roles/optimizer.py`
- Create: `evo/factorio/prompts/optimizer.md`（独立完整 prompt，吸收原 addendum 内容并补全证据消费段）
- Delete: `evo/factorio/prompts/optimizer-addendum.md`（内容已迁入新 prompt）
- Test: `palimpsest/tests/test_role_resolution.py` 加一条 case

**改动要点:**

A. `evo/factorio/roles/optimizer.py`，结构对齐 `evo/default/roles/optimizer.py`（repoless preparation, skip publication），但加载自己的 prompt：

```python
"""Factorio-specific optimizer role.

Reads observation evidence (tool_name, arg_pattern, call_count, similarity, bundle)
and produces a ReviewProposal targeting factorio/scripts/ for tool evolution.
For dispatcher tools, the dispatched script name is encoded as `arg_pattern`.
"""
from __future__ import annotations

from palimpsest.config import WorkspaceConfig
from palimpsest.runtime.roles import JobSpec, context_spec, role


def factorio_optimizer_preparation(**kwargs) -> WorkspaceConfig:
    return WorkspaceConfig(repo="", new_branch=False)


def factorio_optimizer_publication(**kwargs) -> tuple[None, list]:
    return None, []

factorio_optimizer_publication.__publication_strategy__ = "skip"


@role(
    name="optimizer",
    description="Factorio tool-evolution optimizer (analyzes tool_repetition evidence)",
    role_type="optimizer",
    min_cost=0.1,
    recommended_cost=0.5,
    max_cost=1.0,
)
def optimizer(**params) -> JobSpec:
    return JobSpec(
        preparation_fn=factorio_optimizer_preparation,
        context_fn=context_spec(
            system="factorio/prompts/optimizer.md",
            sections=[],  # evidence 走 role_params, 不走 context section
        ),
        publication_fn=factorio_optimizer_publication,
        tools=[],
    )
```

B. `evo/factorio/prompts/optimizer.md` —— 自包含的 prompt，关键段落：

- 输入说明：`metric_type`、`evidence` (list of observation payloads)、`window_hours`、`observation_count`
- **Evidence schema 说明**（重要）：`evidence[i]` 是一条 `ObservationToolRepetitionEvent` payload，字段为 `{role, bundle, tool_name, call_count, arg_pattern, similarity}`。对 `factorio_call_script`，编码约定：
  - `tool_name = "factorio_call_script(<script_name>)"` —— dispatcher 名加括号包了脚本名
  - `arg_pattern = "<script_name>"` —— **此字段名是历史遗留；对 dispatcher tool 它存的是 script name，不是 args 模式**
  - 例：`find_ore_basic` 重复调用 10 次会编码为 `tool_name="factorio_call_script(find_ore_basic)"`, `arg_pattern="find_ore_basic"`, `call_count=10`
- 任务说明：从 evidence 提取 script name（即 `arg_pattern` 字段），识别"高频低封装动作"，提议在 `factorio/scripts/` 下新建一个更高层的封装
- 输出格式：完整 ReviewProposal JSON schema，重点 example 是 `tool_repetition (arg_pattern=find_ore_basic, call_count=10)` → `improve_tool` → 在 `factorio/scripts/` 下新建 `scan_resources_in_radius.lua`
- 路径约束：所有 `task_template.goal` 必须明确指定 `factorio/scripts/<new_script>.lua`，不要再用 `evolved/scripts/`
- bundle 约束：`task_template.bundle` 必须是 `"factorio"`，role 必须是 `"implementer"`

把原 `optimizer-addendum.md` 的内容融入这份新 prompt（具体例子、关键点、分析流程都搬过来），同时新增"如何消费 params.evidence"和"arg_pattern 编码约定"两段。

C. 因为 RoleManager 是 bundle-only 解析（`palimpsest/runtime/roles.py:199`），`evo/factorio/roles/optimizer.py` 一存在，factorio bundle 下的 role="optimizer" 就会命中它。default optimizer 不受影响（其它 bundle 还可以继续用）。

**Steps:**

- [ ] 2.1 创建 `evo/factorio/roles/optimizer.py`（如上结构）。
- [ ] 2.2 创建 `evo/factorio/prompts/optimizer.md`，整合 addendum 内容并新增 evidence 消费段。
- [ ] 2.3 删除 `evo/factorio/prompts/optimizer-addendum.md`。
- [ ] 2.4 跑 role 解析测试：
  ```bash
  cd palimpsest && pytest tests/test_role_resolution.py -k optimizer -v
  ```
- [ ] 2.5 离线手测：用 palimpsest CLI 直接跑一个 factorio optimizer job，goal/params 模拟一条 tool_repetition evidence（`tool_name="factorio_call_script(find_ore_basic)"`, `arg_pattern="find_ore_basic"`, `call_count=10`, `bundle="factorio"`），观察 summary 输出的 ReviewProposal 是否：(a) action_type=improve_tool, (b) task_template.goal 指向 factorio/scripts/，(c) task_template.bundle=factorio。
- [ ] 2.6 commit：`feat(factorio): add bundle-specific optimizer role with evidence-aware prompt`

**完成标志:** 给定一条合成 evidence，factorio optimizer 输出的 ReviewProposal 是 improve_tool + factorio/scripts/xxx.lua 路径。

---

## Task 3: Implementer 工作空间 = live evo_root（option b: workspace_override）

**目标:** 给 `WorkspaceConfig` 加 `workspace_override` 字段；preparation 阶段如果检测到该字段非空，跳过 mkdtemp 直接把 workspace 设成那个路径；finalization 阶段如果检测到 workspace 是 override 来的就跳过 rmtree；factorio 的 implementer role 用这个机制让 workspace 等于 evo_root，bash tool 的 cwd 自然落在 bundle 内。

**Files:**
- Modify: `yoitsu-contracts/src/yoitsu_contracts/config.py`（`WorkspaceConfig` 真正定义处，第 11 行起；Pydantic BaseModel）
- Modify: `palimpsest/palimpsest/stages/preparation.py`（约第 62 行，honor workspace_override）
- Modify: `palimpsest/palimpsest/stages/finalization.py`（约第 30 行，rmtree 处加守卫；这是真正执行删除的位置）
- Modify: `palimpsest/palimpsest/runner.py`（约第 245 行，cleanup 调用处把 override 信号传给 finalization）
- Create: `evo/factorio/lib/preparation.py`（building block 模块）
- Modify: `evo/factorio/roles/implementer.py`（用新 building block）
- Modify: `evo/factorio/prompts/implementer.md`（写入语义说明）
- Test: `palimpsest/tests/` 新增/扩展测试覆盖 workspace_override + cleanup 守卫
- 注意: `palimpsest/palimpsest/config.py` 是个 re-export shim，不需要改；它会自动暴露新字段

**改动要点:**

A. `yoitsu-contracts/src/yoitsu_contracts/config.py:11`（Pydantic BaseModel，**不是** dataclass）：
```python
class WorkspaceConfig(BaseModel):
    """Configuration for job preparation (renamed to PreparationConfig per ADR-0009)."""
    repo: str = ""
    init_branch: str = "main"
    new_branch: bool = True
    depth: int = 1
    git_token_env: str = ""
    input_artifacts: list[ArtifactBinding] = Field(default_factory=list)
    workspace_override: str = ""  # NEW: if set, preparation uses this path; finalization will not rmtree it

# PreparationConfig 已是 WorkspaceConfig 的别名，自动获得新字段
```

B. `palimpsest/palimpsest/stages/preparation.py` 约第 62 行：
```python
# 旧
workspace_path = tempfile.mkdtemp(prefix="palimpsest-")
logger.info(f"Created workspace: {workspace_path}")
if config.repo:
    ...clone...

# 新
if config.workspace_override:
    workspace_path = config.workspace_override
    logger.info(f"Using workspace override: {workspace_path}")
    if config.repo:
        raise ValueError("workspace_override and repo are mutually exclusive")
    # 不创建目录、不 clone；调用方保证路径已存在
else:
    workspace_path = tempfile.mkdtemp(prefix="palimpsest-")
    logger.info(f"Created workspace: {workspace_path}")
    if config.repo:
        ...clone（保持原逻辑）...
```

C. `palimpsest/palimpsest/stages/finalization.py:14`——`finalize_workspace_after_job` 是真正执行 `shutil.rmtree(workspace_path)` 的函数，目前只受 `PALIMPSEST_KEEP_WORKSPACE` 环境变量保护。当前签名：
```python
def finalize_workspace_after_job(
    workspace_path: str,
    gateway: EventGateway | None = None,
    *,
    keep_env: str = "PALIMPSEST_KEEP_WORKSPACE",
) -> str | None:
    ...
```
加一个 keyword-only `is_override: bool = False` 形参，True 时**优先于** `PALIMPSEST_KEEP_WORKSPACE` 直接 return：
```python
def finalize_workspace_after_job(
    workspace_path: str,
    gateway: EventGateway | None = None,
    *,
    keep_env: str = "PALIMPSEST_KEEP_WORKSPACE",
    is_override: bool = False,  # NEW: 阻止删除 workspace_override 路径
) -> str | None:
    if is_override:
        logger.info(f"Skipping cleanup for override workspace: {workspace_path}")
        return None
    if os.environ.get(keep_env, "").strip() in {"1", "true", "yes"}:
        ...
    shutil.rmtree(workspace_path)
    ...
```

D. `palimpsest/palimpsest/runner.py`——关键路径修正：`workspace_override` 是 role 的 `preparation_fn` 返回的 `WorkspaceConfig` 上的字段，不是 `JobConfig` 上的静态配置。当前 runner 流程（约 141-155 行）是：
```python
workspace_cfg = spec.preparation_fn(**prep_params)  # ← 这里返回的 cfg 带 workspace_override
workspace = setup_workspace(job_id, workspace_cfg, ...)
```
所以在 `finally` 块里（约 245 行）不能从 `config` 读 override 信号，必须从 `workspace_cfg` 或一个缓存变量读。建议在 preparation 后立刻缓存：
```python
# 约第 155 行，preparation 之后
is_override_workspace = bool(workspace_cfg.workspace_override)

# 然后在 finally 块（约 245 行）：
finalize_workspace_after_job(
    workspace,
    gateway=gateway,
    is_override=is_override_workspace,  # 用缓存的局部变量
)
```
如果嫌缓存变量不够优雅，也可以让 `setup_workspace` 在 override 情况下返回时给 workspace 加一个 sentinel 文件或属性，但这会更绕。用局部变量是最清晰的方式。**注意：`workspace_cfg` 变量要在 try/finally 结构的外层定义（或用 `locals()` 查），否则 finally 块里可能访问不到。**

C. `evo/factorio/lib/preparation.py` —— 新模块，第一个 building block：
```python
"""Reusable preparation building blocks for Factorio bundle.

Each function returns a WorkspaceConfig (or operates on runtime_context as a side effect).
Roles compose these in their own preparation_fn. Future plan: replace per-role
preparation_fn with a list of these building blocks.
"""
from __future__ import annotations

from palimpsest.config import WorkspaceConfig


def prepare_evo_workspace_override(*, evo_root: str, **kwargs) -> WorkspaceConfig:
    """Make the live evo_root the agent's workspace.
    
    Used by implementer-style roles that should write directly into the bundle.
    Caller is responsible for ensuring serialization (factorio bundle has a serial lock).
    """
    return WorkspaceConfig(repo="", new_branch=False, workspace_override=evo_root)
```

D. `evo/factorio/roles/implementer.py` —— 用 building block 替换原 git 路径：
```python
from __future__ import annotations

from palimpsest.runtime.roles import JobSpec, context_spec, role
from factorio.lib.preparation import prepare_evo_workspace_override


def implementer_publication(**kwargs) -> tuple[None, list]:
    return None, []

implementer_publication.__publication_strategy__ = "skip"


@role(
    name="implementer",
    description="Factorio bundle implementer (writes lua directly into the live bundle)",
    role_type="worker",
    min_cost=0.1,
    recommended_cost=0.5,
    max_cost=1.5,
)
def implementer(**params) -> JobSpec:
    return JobSpec(
        preparation_fn=prepare_evo_workspace_override,
        context_fn=context_spec(
            system="factorio/prompts/implementer.md",
            sections=[{"type": "factorio_scripts"}],
        ),
        publication_fn=implementer_publication,
        tools=["bash"],
    )
```

E. `evo/factorio/prompts/implementer.md`：明确且自洽地写出工作目录约定：

> 你的当前工作目录（cwd）就是 evo_root。bundle 内所有文件都在 `factorio/` 子目录下。新脚本写到 `factorio/scripts/<your_script>.lua`（相对 cwd 的路径，等价于 `<evo_root>/factorio/scripts/<your_script>.lua`）。**不要**写到 `factorio/` 之外的任何目录；**不要**修改已有的 `factorio/scripts/actions/`、`factorio/scripts/atomic/`、`factorio/scripts/lib/`、`factorio/scripts/examples/` 下的文件，只创建新文件。

不要给 agent 留任何"workspace 是 factorio 还是 evo_root"的歧义；唯一正确的描述是"cwd = evo_root，新脚本相对路径以 `factorio/scripts/` 开头"。

F. **路径白名单怎么办?** 留 TODO，不在本任务做。理由：bundle 容器隔离已经把文件系统能写入的范围限定在 evo_root 内，且本任务会在两个 trenni config 里给 factorio bundle 显式加 `max_concurrent_jobs=1` 防止并发写入冲突（见步骤 3.0）。Task 3 提交时在 commit message 和 implementer prompt 末尾加 TODO 注释。

G. **factorio bundle 串行化配置（前置安全措施）**：当前 `config/trenni.yaml` 没有 `bundles` 段，`deploy/quadlet/trenni.dev.yaml` 也只有全局 `max_workers: 1`。`BundleSchedulingConfig` 在 `trenni/trenni/config.py` 里已经定义，`tests/test_scheduler_capacity.py` 已示范了用法。本任务给两个 yaml 都加上：
```yaml
bundles:
  factorio:
    scheduling:
      max_concurrent_jobs: 1
```
这是 `workspace_override` 安全性的第二道防线。**先做这个，再做后面任何 workspace_override 相关改动**。

**Steps:**

- [ ] 3.0 **（前置安全措施，先做）** 给 `config/trenni.yaml` 和 `deploy/quadlet/trenni.dev.yaml` 加 `bundles.factorio.scheduling.max_concurrent_jobs: 1`。校验：
  ```bash
  cd trenni && pytest tests/test_scheduler_capacity.py -v
  ```
  本步骤独立成 commit：`config: serialize factorio bundle (max_concurrent_jobs=1) ahead of workspace_override rollout`
- [ ] 3.1 在 `yoitsu-contracts/src/yoitsu_contracts/config.py` 的 `WorkspaceConfig` 加 `workspace_override: str = ""` 字段（Pydantic field，不要用 dataclass 语法）。
- [ ] 3.2 改 `palimpsest/palimpsest/stages/preparation.py`：检测 override 字段，跳过 mkdtemp，加 `repo + override` 互斥校验。
- [ ] 3.3 改 `palimpsest/palimpsest/stages/finalization.py:finalize_workspace_after_job`：加 `is_override: bool = False` 形参，True 时直接 return（在 `PALIMPSEST_KEEP_WORKSPACE` 检查之前）。
- [ ] 3.4 改 `palimpsest/palimpsest/runner.py` cleanup 调用点（约 245 行）：不要从 `config` 读 override 信号；在 preparation 后缓存 `is_override_workspace = bool(workspace_cfg.workspace_override)`，再把 `is_override=is_override_workspace` 传给 `finalize_workspace_after_job(...)`。先 grep 一遍 `finalize_workspace_after_job(` 调用确保所有调用点都改到了。
- [ ] 3.5 grep 全仓 `rmtree` 和 `finalize_workspace_after_job`，确认没有遗漏的删除路径会绕过守卫。
  ```bash
  rg -n "rmtree|finalize_workspace_after_job" palimpsest/ trenni/
  ```
- [ ] 3.6 创建 `evo/factorio/lib/preparation.py` 和 `prepare_evo_workspace_override`。
- [ ] 3.7 重写 `evo/factorio/roles/implementer.py`：删 git 相关 import / 函数，用 building block 替换 preparation_fn，publication 改 skip。
- [ ] 3.8 改 `evo/factorio/prompts/implementer.md`：去掉 git/branch 流程描述，加 bundle 内写入说明（"workspace 就是 evo_root，新文件写到 `factorio/scripts/<name>.lua`"）。
- [ ] 3.9 单测：preparation 测试加用例 `WorkspaceConfig(workspace_override="/tmp/foo")` → `workspace_path == "/tmp/foo"`，没有 mkdtemp 调用（mock tempfile.mkdtemp）。
- [ ] 3.10 单测：`workspace_override` 和 `repo` 同时设置时 preparation 抛 ValueError。
- [ ] 3.11 单测：finalization `finalize_workspace_after_job(path, is_override=True)` 不调用 `shutil.rmtree`（mock 验证）。
- [ ] 3.12 跑 palimpsest 全量测试：
  ```bash
  cd palimpsest && pytest -q
  ```
- [ ] 3.13 **干净仓库手测（阻塞性，防止灾难）**：在一个独立的 git clone 上触发一个最小 implementer 任务（goal "在 factorio/scripts/ 下创建 hello.lua"），任务结束后用 `git status` 确认 evo_root 完好无损，新文件确实出现在 `<clone>/evo/factorio/scripts/hello.lua`，且 evo_root 没被任何方式动过其他东西。
- [ ] 3.14 commit：`feat(contracts): add WorkspaceConfig.workspace_override`, `feat(palimpsest): honor workspace_override in preparation/finalization`, `feat(factorio): implementer writes to live bundle`（建议拆三个 commit）

**完成标志:** Task 3.13 的手测能通过，新文件实际落在 evo_root 下。

---

## Task 4: Worker preparation — 基于 building block 重建 Factorio 运行环境

**目标:** worker 跑 job 之前，把当前 bundle 的 `factorio/scripts/` 同步进 Factorio server 的 mod 脚本目录、触发 `/reload`（或等价机制），再连 RCON。把这一串拆成 building block，worker.preparation_fn 是它的薄壳。

**Files:**
- Modify: `evo/factorio/lib/preparation.py`（追加新的 building block）
- Modify: `evo/factorio/roles/worker.py`（用新 building block）
- Modify or new: `evo/factorio/lib/rcon.py`（如果 reload 命令封装放这里）
- Test: `evo/factorio/tests/` 或 `palimpsest/tests/` 相关测试（mock RCON）

**改动要点:**

A. building block 设计——把"启 RCON + 加载 mod"和"原始 RCON 连接"分开，方便后续组合：

```python
# evo/factorio/lib/preparation.py 追加

def prepare_factorio_runtime(
    *,
    runtime_context,
    evo_root: str,
    **kwargs,
) -> WorkspaceConfig:
    """Sync bundle scripts into the live Factorio mod, reload, then connect RCON.
    
    Effects:
    - Copies/syncs evo_root/factorio/scripts/ -> $FACTORIO_MOD_SCRIPTS_DIR
    - Issues a reload command via RCON
    - Stores RCONClient in runtime_context.resources["rcon"]
    - Registers cleanup to close RCON
    
    Returns:
        Empty WorkspaceConfig (worker doesn't need a workspace).
    """
    import os
    import shutil
    from pathlib import Path
    from factorio.lib.rcon import RCONClient

    src = Path(evo_root) / "factorio" / "scripts"
    dst_env = os.environ.get("FACTORIO_MOD_SCRIPTS_DIR")
    if not dst_env:
        raise RuntimeError(
            "FACTORIO_MOD_SCRIPTS_DIR must point to the live Factorio mod scripts directory"
        )
    dst = Path(dst_env)
    if not src.exists():
        raise RuntimeError(f"Bundle scripts dir missing: {src}")
    
    # Safety checks before destructive rmtree
    # Per plan review: prevent accidental deletion from misconfigured dst
    if dst.exists():
        if dst == src:
            raise RuntimeError(f"dst == src, refusing to delete: {dst}")
        if str(dst) in ("/", "/usr", "/home", "/opt", "/var"):
            raise RuntimeError(f"dst is a system root directory, refusing to delete: {dst}")
        # Verify dst looks like a Factorio mod scripts directory
        # Expected: .../factorio-agent/scripts or similar; reject if doesn't end in scripts
        if dst.name != "scripts":
            raise RuntimeError(
                f"dst path does not end in 'scripts', suspicious configuration: {dst}"
            )
        # Additional safety: refuse if dst has more than 100 files (unlikely for scripts dir)
        file_count = sum(1 for _ in dst.rglob("*") if _.is_file())
        if file_count > 100:
            raise RuntimeError(
                f"dst has {file_count} files (>100), refusing to delete (suspicious): {dst}"
            )
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    # Connect RCON
    rcon = RCONClient(
        host=os.environ.get("FACTORIO_RCON_HOST", "localhost"),
        port=int(os.environ.get("FACTORIO_RCON_PORT", "27015")),
        password=os.environ.get("FACTORIO_RCON_PASSWORD", "changeme"),
    )
    rcon.connect()
    runtime_context.resources["rcon"] = rcon
    runtime_context.register_cleanup(rcon.close)

    # Reload mod scripts so freshly synced files take effect
    # Note: RCONClient exposes send_command(), not command()
    rcon.send_command("/silent-command pcall(function() game.reload_script() end)")

    return WorkspaceConfig(repo="", new_branch=False)
```

B. `evo/factorio/roles/worker.py` 替换原 `factorio_worker_preparation`：

```python
from factorio.lib.preparation import prepare_factorio_runtime

@role(
    name="worker",
    description="Factorio in-game worker with RCON",
    role_type="worker",
    min_cost=0.1,
    recommended_cost=0.5,
    max_cost=2.0,
)
def worker(**params) -> JobSpec:
    return JobSpec(
        preparation_fn=prepare_factorio_runtime,
        context_fn=context_spec(
            system="factorio/prompts/worker.md",
            sections=[{"type": "factorio_scripts"}],
        ),
        publication_fn=factorio_worker_publication,  # 保留原 skip 实现
        tools=["factorio_call_script"],
    )
```

C. **关于 reload 机制**：`/silent-command` + `game.reload_script()` 是 Factorio 的标准热重载入口；如果 mod 用的 require 缓存导致 reload 不彻底，fallback 是直接重启 server（更重，不在 MVP 做）。本任务先实现热重载路径，把"重启 server"作为已知 fallback 写进风险表。

D. 新脚本可见性：因为 sync 是把整个 `factorio/scripts/` 复制到 mod 的 scripts 目录，再 reload，新文件**自动**进入 mod 的 require path。`factorio_scripts` context section（`evo/factorio/contexts/factorio_scripts.py:25`）扫的是 bundle 的 `factorio/scripts/`，所以 worker prompt 看到的 catalog 已经包含新文件。无需修改 catalog 扫描。

E. **`factorio_call_script` 注册问题**：当前实现要求脚本必须已在 mod 里注册。如果 reload 后脚本自动可用就 OK；如果 mod 控制层有显式的脚本白名单（比如只暴露 `actions/*` 这种 namespace），需要在 mod 控制端做相应放宽——但这是 mod 侧的工作，不在本计划代码范围。本任务收尾前要在 mod 仓库也提一个 PR 或说明所需变更，记录在 runbook 里。

**Steps:**

- [ ] 4.1 在 `evo/factorio/lib/preparation.py` 追加 `prepare_factorio_runtime`。
- [ ] 4.2 改 `evo/factorio/roles/worker.py` 用新 building block；保留 `factorio_worker_publication`。
- [ ] 4.3 单测：mock `RCONClient` 和 `shutil.copytree`，断言 sync → connect → reload 顺序，并断言 cleanup 注册。
  ```bash
  cd palimpsest && pytest tests/ -k factorio_runtime -v
  ```
- [ ] 4.4 手测：先让 implementer 在 `factorio/scripts/` 下写一个简单脚本（比如 `hello.lua`，内容只 print），然后 trigger 一个 worker 任务执行 `factorio_call_script(name="hello")`，验证 reload 后 worker 能调用成功。
- [ ] 4.5 文档：在 `docs/runbooks/`（或本计划末尾）记录 mod 端需要的配套调整（如有），含 `FACTORIO_MOD_SCRIPTS_DIR` 环境变量约定。
- [ ] 4.6 commit：`feat(factorio): worker preparation reloads bundle scripts into live mod`

**完成标志:** 4.4 手测通过——新写入的 lua 文件经 worker preparation 后能被 factorio_call_script 调用。

---

## Task 5: 50 铁矿端到端 smoke

**目标:** 用真实 Factorio 任务跑通完整链路，验证 MVP 成功标志。

**Files:**
- 可能新增/调整: `smoke/` 或 `test-tasks/` 下的 task 模板
- 不改代码，纯运行 + 观察 + 留底

**前置条件:**
- Task 1-4 全部 commit 通过
- Factorio headless server 可达，挖矿机和铁矿地图就绪
- `FACTORIO_MOD_SCRIPTS_DIR` 环境变量已配置
- bundle 的 `factorio/scripts/` 当前存在 `actions/` 下基础动作（包括类似 `find_ore_basic` 的脚本）

**Steps:**

- [x] 5.1 准备任务输入：goal "用挖矿机挖 50 个铁矿"，bundle=factorio，role=worker。
  - 2026-04-08 实际触发 payload: `trigger.manual` with `goal="用挖矿机挖 50 个铁矿"`, `bundle="factorio"`, `role="worker"`
  - 生成的 worker task/job: `aa4bb0753bad0a44` / `aa4bb0753bad0a44-root`
- [x] 5.2 第一轮：触发任务，等其结束。**记录:**
  - 总 step 数（期望 ~10-15）
  - tool_pattern 是否触发 `observation.tool_repetition` 事件（期望: 是，`arg_pattern` 等于触发任务里反复调用的脚本名，例如 `find_ore_basic`）
  - aggregator 是否触发 optimizer spawn（期望: 是，且 trigger_data.bundle="factorio"）
  - factorio optimizer 输出的 ReviewProposal（期望: action_type=improve_tool, task_template.goal 指向 `factorio/scripts/<某个 radius scan 类脚本>.lua`, bundle=factorio）
  - implementer 子任务是否成功结束（期望: 是，新 lua 文件实际出现在 evo_root 下）
- [x] 5.3 验证文件：`ls evo/factorio/scripts/` 应包含新脚本；内容看起来像 radius scan 实现（功能完美与否不验证）。
  - 2026-04-08 初次观察结果：**未通过**。
  - factorio optimizer task/job: `ea81cdc120cf1496` / `ea81cdc120cf1496-root`
  - proposal-spawned implementer task/job: `069d65f1b5ad760e` / `069d65f1b5ad760e-root`
  - implementer summary 声称已创建 `factorio/scripts/scan_resources_in_radius.lua`
  - 初始根因 1：job image 过旧，implementer 实际写到了 `/tmp/palimpsest-*`
  - 修复后再次验证通过：`scan_resources_in_radius.lua` 已出现在 `evo/factorio/scripts/`
- [x] 5.4 第二轮：再触发同一任务。worker preparation 应触发 reload，使新脚本生效。
  - 初始根因 2：worker job 只有 `FACTORIO_MOD_SCRIPTS_DIR` 环境变量，没有宿主 RW bind mount，导致同步只发生在容器私有文件系统
  - 后续根因 3：加上 RW bind mount 后，`prepare_factorio_runtime()` 试图 `rmtree()` 挂载点本身，触发 `[Errno 16] Device or resource busy`
  - 修复后验证通过：`/home/holo/factorio/mods/factorio-agent_0.1.0/scripts/scan_resources_in_radius.lua` 已出现，说明 worker preparation 的同步路径已打通
  - 但本次第二轮任务 `e42bfc511e9cc544` 直接发现库存已有 50 个铁矿，因此**未能形成有效的步数下降对比样本**
- [x] 5.5 把第一轮和第二轮的 trajectory + step 数 + lua 产物存到 `docs/runbooks/2026-04-07-factorio-optimization-loop-closure-runbook.md` 留底。
  - 2026-04-08 已记录第一轮 live 证据、collision fix、以及当前 blocker。
- [ ] 5.6 在本计划顶部加 ✅ 完成标记，TODO.md 划掉对应条目。
  - 说明：链路与脚本同步已验证通过，但“步数显著下降”的成功标准仍需在清理库存/重置环境后重新测量。

**完成标志:** 两轮 step 数对比成立，全程无人工干预。MVP 标志达成。

---

## 风险与回退

| 风险 | 影响 | 缓解 |
|---|---|---|
| `WorkspaceConfig.workspace_override` 与现有 cleanup 逻辑冲突，误删 evo_root | 灾难性（丢代码） | Task 3.3 必做：grep 所有 `rmtree(workspace)` 加守卫；commit 前在干净 git 仓库手测验证 evo_root 没被动 |
| Implementer 没白名单，可能写到 bundle 之外 | 安全/隔离 | 容器隔离 + Step 3.0 给 factorio bundle 显式 `max_concurrent_jobs=1`（不再依赖"全局 max_workers=1"这种隐式串行）；Task 3 commit message 明确写 TODO，跑通 smoke 后立刻补 snapshot diff |
| `game.reload_script()` 在带 require 缓存的 mod 里 reload 不彻底 | 新脚本不生效 → Task 5 卡死 | 备用方案：先 stop server → sync → start server。重启 server 写进 Task 4 风险段 |
| Observation 事件不带 bundle 字段，bundle 路由 fallback 到 default | factorio optimizer 永远不被命中 | Task 1 验证步骤里专门确认 evidence 携带 bundle；如不带，方案是让 aggregator 按 bundle 分桶订阅 |
| Optimizer 拿到 evidence 但仍输出 generic 提案 | 闭环逻辑通但产出无价值 | Task 2.5 离线手测就要先用 mock evidence 验证；prompt 必须强制 example 是 improve_tool |
| `factorio_call_script` mod 侧白名单卡住新脚本 | 第二轮 worker 调用失败 | Task 4.5 必须把 mod 端配套要求写清楚；如果 mod 不配合，先在 mod 端临时全开 |
| Task 5 第一轮地图运气好只跑 1-2 步 | 无法验证优化效果 | 选 spawn 远离铁矿的存档；或在 trigger 时强制 worker 用 `find_ore_basic` 单步策略 |

---

## 不在本计划范围内（明确留给 Phase 2+）

- role.preparation_fn → 多个 building block 组合的 list 形态
- 把 factorio mod 源码搬进 `evo/factorio/mod/`
- 引入独立 eval role + trajectory reflection
- implementer 路径白名单 snapshot diff 实现
- artifact-linked 优化目标
- 自定义 observation event types
- ADR-0010/0014 文档同步
