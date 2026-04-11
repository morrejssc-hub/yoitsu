# Yoitsu 架构指南

**Status**: Active · **Last Updated**: 2026-04-10
**Anchor ADRs**: [ADR-0015](adr/0015-bundle-as-repo.md), [ADR-0016](adr/0016-capability-model.md), [ADR-0017](adr/0017-observation-unified-interface.md)

本文档是系统架构的唯一权威参考。当其他文档与本文冲突时，以本文为准。

> **术语迁移声明**：本架构已采用 **Bundle** 作为配置、调度、观测、并发控制的基本单位，取代了早期设计中的 **Team** 概念。所有使用 Team 的旧 ADR（如 archive/adr/0003-runtime-execution.md、archive/adr/0012-factorio-task-source-old.md）应视为历史参考。Team 的 runtime isolation 语义已迁移至 Bundle 的 runtime 配置；Team 的 evo 目录结构已迁移至 Bundle Repo。

---

## 1. 核心原则

### 1.1 Event Store 是唯一因果权威

Event Store 是系统的唯一因果权威。它回答"谁在何时声明了什么"，不回答"那个东西现在在哪里、是否还活着"。

- 采用 append-only 模式记录所有生命周期事件、观察信号、工具调用和 LLM 判断
- Pasloe 是其实现
- 任何不记录到 Event Store 的中间状态不应对后续决策产生影响

### 1.2 Content Authority 按 URI Scheme 分布式承担

不存在统一的内容存储模块。内容的持久化和可达性由 URI scheme 背后的系统各自承担：

| Scheme | Content Authority | 典型用途 |
|---|---|---|
| `inline:` | Event payload 自身 | 小数据（观察事件、job metadata） |
| `file://` | 文件系统 | Factorio save、日志归档 |
| `git+file://` / `git+ssh://` / `git+https://` | Git 托管 | Bundle 仓库快照、代码产物 |
| `http(s)://` | 上游服务 | 外部文档、数据集 |

Event Store 忠实记录 URI 字符串，不解引用、不拉取、不校验字节可达性。

### 1.3 Artifact 是 First-Class 概念

Artifact 是系统中任何被 event 引用过的持久对象。它由三个属性定义：

1. **身份** = URI 字符串
2. **因果记录** = Event Store 中声明该 artifact 的事件
3. **可用性** = Content Authority（按 scheme 各自负责）

Artifact 不是某个存储模块的记录，也不是某个组件的内部状态。它是跨组件可见的被引用实体。

> **注意**：Artifact 的物理形态由 URI scheme 决定。Bundle 仓库快照、Factorio save 文件、日志归档、外部数据集都是 artifact。

---

## 2. 系统组件

### 2.1 Pasloe (Event Store)

系统的时序/因果权威。Schema-agnostic 的事件总线。

- 两阶段流水线：事件写入先获得 `accepted`（持久性边界），随后异步进入 `committed`（消费者可见）
- 在任务语义层提供盲派发
- 不持有 bundle 内容、save 文件、大对象

### 2.2 Trenni (控制面)

确定性的事件驱动调度引擎，分为两层：

**Task 调度层**：将 task 物化为 job 的 DAG。

- 消费 trigger 事件和 spawn 事件
- 管理 task 状态机（`pending → running → evaluating → completed/failed/partial`）
- `spawn()` 是唯一的编排原语：Agent 调用 `spawn(tasks=[...])` → Trenni 展开为子 Task + Job + 可选 Join Job
- 任务分解决策属于 Planner 角色（LLM 判断），不属于 Trenni

**Job 调度层**：将 job 请求映射到具体执行。

- 解析 bundle source（selector → commit sha）
- 物化 workspace（ephemeral clone）
- 启动容器（可切换后端：Podman、K8s 等）
- Job 完成后回收 workspace

**Observation 分析**：Job 完成后执行后置分析（详见 §6）。

**运行约束**：

- 摄取/执行分相：摄取失败回滚 cursor，执行失败不回滚
- Trenni → Palimpsest 单向推送（JobConfig 序列化注入容器环境变量）

### 2.3 Palimpsest (Runtime)

一次性、短寿命的无状态执行容器。一次运行定义为一个 **Job**。

运行四阶段流水线（详见 §4）：

1. **Preparation** — capability setup
2. **Context** — LLM 上下文组装
3. **Agent Loop** — LLM 循环 + tool dispatch
4. **Finalization** — capability finalize + 事件代发

Palimpsest 消费 Trenni 通过 JobConfig 传入的两个 workspace：

- `BundleSource.workspace`：bundle repo 的 ephemeral clone，用于加载 roles/capabilities/tools
- `TargetSource.workspace`：目标仓库的 ephemeral clone（可选），用于 agent 执行任务

### 2.4 yoitsu-contracts

隔离并收拢上述三个组件的共有数据契约、协议与事件基础原型定义。

---

## 3. Bundle 模型

### 3.1 Bundle

一组为某一类任务服务的可复用资产的**逻辑身份**，以稳定字符串名称标识（如 `"factorio"`、`"webdev"`）。Bundle 是配置、调度、观测、并发控制的基本单位。

Bundle **不是** URL、目录、git 仓库。这些是 bundle 的物理化形式，可以更换；bundle 名称本身是稳定的逻辑锚点。

### 3.2 Bundle Repo

承载某个 bundle 的 code-like 内容的**独立 git 仓库**。每个 bundle 有且仅有一个 bundle repo，是该 bundle 内容的权威来源。

```
factorio-bundle/
├── bundle.yaml          # 元数据 + 声明式 artifacts
├── capabilities/        # setup + finalize 生命周期管理
├── roles/               # role 定义（声明 needs + contexts）
├── contexts/            # context provider（LLM 上下文组装）
├── tools/               # bundle 私有工具
├── prompts/             # prompt 文件
├── observations/        # observation analyzer（注册到 Trenni）
├── scripts/             # bundle 私有代码
├── lib/                 # 共用工具库
└── examples/            # 可选示例
```

其中 `roles/` `tools/` `contexts/` 为 runtime 强依赖的最小必需集合；`capabilities/` `observations/` 为本次架构重构新增的标准目录；其余为 bundle 自主决定的扩展空间。

### 3.3 Bundle Source

一次 job 执行时对 bundle 来源的运行时描述：

| 字段 | 含义 |
|---|---|
| `name` | 逻辑身份（如 `"factorio"`） |
| `repo_uri` | bundle 仓库远端地址 |
| `selector` | 配置中声明的分支名或 tag 名（意图声明） |
| `resolved_ref` | Trenni 解析出的 commit sha（执行定格） |
| `workspace` | Trenni 物化出的 ephemeral 目录路径 |

`selector` 是"意图声明"（我想用 evolve 分支的最新状态），`resolved_ref` 是"执行定格"（实际 checkout 了 sha a1b2c3d）。`resolved_ref` 由 Trenni 在派发 job 前动态解析，保证可复现性。

Bundle Source 是 per-job 的运行时产物，不是静态配置项。

### 3.3.1 Target Source

一次 job 执行时对**任务目标仓库**的运行时描述（可选）：

| 字段 | 含义 |
|---|---|
| `repo_uri` | 目标仓库远端地址 |
| `selector` | 初始分支或 tag 名 |
| `resolved_ref` | Trenni 解析出的 commit sha |
| `workspace` | Trenni 物化出的 ephemeral 目录路径 |

**与 Bundle Source 的区别**：

| | Bundle Source | Target Source |
|---|---|---|
| **内容** | bundle repo（roles/capabilities/tools） | 目标仓库（agent 要修改的代码） |
| **用途** | runtime 加载可执行代码 | agent 执行任务、读写文件 |
| **必需性** | 必需 | 可选（planner/root eval 无目标仓库） |
| **artifact URI 指向** | 不产生 artifact | `git+ssh://repo@sha` 指向远端 |

**Workspace 归属说明**：

- `ctx.bundle_workspace` = BundleSource.workspace，用于加载 bundle 代码
- `ctx.target_workspace` = TargetSource.workspace，用于 agent 执行任务
- 两者都是 ephemeral，job 结束后回收
- **artifact.published.ref 必须指向远端仓库 URI**，不能指向 ephemeral workspace 路径

### 3.4 Bundle Registry

Trenni 配置中按 bundle 名键控的映射：

```yaml
bundles:
  factorio:
    source:
      url: "git+file:///home/holo/bundles/factorio-bundle.git"
      selector: evolve
    runtime: { ... }
    scheduling: { ... }
  webdev:
    source:
      url: "git+ssh://git@github.com/.../webdev-bundle.git"
      selector: main
```

Registry 只记录"这个名字对应哪个仓库和哪条分支/tag"。不存储 commit sha——那是 per-job 的 `resolved_ref`。

### 3.5 Bundle Workspace 与 Target Workspace

Trenni 为每次 job 准备两个独立的 ephemeral workspace：

| Workspace | 来源 | 用途 |
|---|---|---|
| **Bundle Workspace** | BundleSource.workspace | runtime 加载 roles/capabilities/tools |
| **Target Workspace** | TargetSource.workspace | agent 执行任务、读写文件（可选） |

**生命周期**：

- Job 启动前，Trenni clone bundle repo 和目标仓库到两个独立目录
- Job 执行期间，agent 在 Target Workspace 中读写文件
- Finalization 时，git_workspace capability commit + push 到**远端目标仓库**，不是 ephemeral workspace
- Job 结束后，两个 workspace 整体丢弃

**权威归属**：

- Workspace **永远不是权威**
- Artifact URI 必须指向远端仓库（如 `git+ssh://git@github.com/org/repo@sha`），不能指向 ephemeral workspace 路径
- Bundle repo 的演化在 bundle repo 自身的 git 历史中，不在 workspace

**Repoless 任务**（planner、root eval）：TargetSource 为 None，无 Target Workspace。

### 3.6 Declared vs Ad-hoc Artifact

- **Declared artifact**：在 `bundle.yaml` 的 `artifacts` 字段中静态列出。Trenni 启动期可索引、可 lint、可做依赖校验。
- **Ad-hoc reference**：role 运行时产生的未声明 URI 引用，出现在事件的 ref 字段中。

运行时路径上两者完全等价——都是 event 中的 URI 字符串。区别只在**启动期可见性**。

### 3.7 Evolve Branch

Bundle repo 中专供 agent 演化使用的分支约定（如 `evolve` 或 `evolve/*`）。Agent 的 publication 默认 push 到此类分支，与人类维护的 `main` 分支平行。

这是约定（convention），不是 ADR 级别的强制约束。

---

## 4. Runtime 四阶段流水线

Palimpsest 为每个 job 执行以下流水线：

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌────────────────┐
│  Preparation │ →  │   Context    │ →  │  Agent Loop  │ →  │ Finalization   │
│  cap.setup() │    │  context_fn  │    │  LLM + tools │    │ cap.finalize() │
└──────────────┘    └──────────────┘    └──────────────┘    └────────────────┘
```

### 4.1 Preparation

遍历 role 声明的 `needs` 列表，调用每个 capability 的 `setup()`。

典型动作：clone repo、启动服务、建立连接、拷贝脚本。

Capability 不直接发送事件。`setup()` 返回事件数据（如果有），runtime 代发。

**Backward Compatibility**: 如果 `needs=[]`，则回退到旧的 `preparation_fn` 路径。这是为了支持逐步迁移到 capability 模型。新的 role 应使用 capability model，旧的 role 可继续使用 preparation_fn。

### 4.2 Context

调用 `context_fn` 组装 LLM 需要的上下文信息。

Context provider 是纯只读的数据组装：查询 Pasloe 历史、读取脚本目录、组装 prompt 片段。不产生副作用、不发送事件。

Context 和 capability 正交：capability 服务于 runtime 生命周期管理，context 服务于 LLM prompt 组装。两者的消费者不同。

### 4.3 Agent Loop

LLM 循环 + tool dispatch。这是 agent 的核心执行阶段。

退出条件：

- LLM 连续两轮不调用工具（idle detection，详见 [ADR-0002](adr/0002-task-lifecycle-verdict.md)）
- 达到 `max_iterations_hard`
- 达到 `job_timeout`

### 4.4 Finalization

遍历所有激活的 capability，调用 `finalize()`。

典型动作：git commit+push、导出存档、断开连接、停止服务。

每个 capability 的 `finalize()` 内部完成实际工作，返回事件数据（artifact refs、cleanup 确认等），runtime 统一 emit。

**Capability 之间的 finalize 互不依赖。** 如果两个动作有执行顺序要求，它们应该在同一个 capability 内处理。

**Backward Compatibility**: 如果 `needs=[]`，则回退到旧的 `publication_fn` 路径。这是为了支持逐步迁移到 capability 模型。新的 role 应使用 capability model，旧的 role 可继续使用 publication_fn。

---

## 5. Capability 模型

详见 [ADR-0016](adr/0016-capability-model.md)。

### 5.1 定义

Capability 是 bundle 提供的运行时服务管理单元，具有 setup/finalize 生命周期。

```python
class FinalizeResult:
    events: list[EventData]  # "做了什么"的事件数据
    success: bool            # 是否算成功（决定 job 终态）

class Capability(Protocol):
    name: str
    def setup(self, ctx: JobContext) -> list[EventData]: ...
    def finalize(self, ctx: JobContext) -> FinalizeResult: ...
```

- 内部完成实际工作（副作用在函数体内发生）
- 返回事件数据 + success 标志
- Runtime 统一 emit 事件，根据所有 capability 的 `success` 综合决定 job 终态
- Capability 对事件系统无感知

### 5.4 Finalize 错误处理

Finalize 是 job 的最后一道关口，**不允许抛出异常**。每个 finalize 步骤必须有 try-catch 包裹，内部完成重试逻辑，最终返回 `(events, success)`。

```python
def finalize(self, ctx: JobContext) -> FinalizeResult:
    events = []
    success = True
    
    # 重试逻辑在 fn 内部完成
    for attempt in range(MAX_RETRIES):
        try:
            result = self._do_publish(ctx)
            events.append(EventData(type="artifact.published", data=result))
            return FinalizeResult(events=events, success=True)
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                continue  # 重试
            # 重试耗尽，记录失败
            events.append(EventData(type="finalize.failed", data={
                "capability": self.name,
                "stage": "publish",
                "error": str(e),
                "attempts": MAX_RETRIES,
                "artifact_persisted": False  # artifact 是否成功持久化
            }))
            success = False
    
    return FinalizeResult(events=events, success=success)
```

**原则**：

1. **重试在 fn 内部完成**：capability 自己决定重试策略，不依赖 runtime
2. **返回 success 标志**：`success=True` 表示该 capability 成功完成，`success=False` 表示失败
3. **事件必须记录**：无论成功或失败，都必须返回事件数据，runtime 必 emit
4. **Job 终态由综合结果决定**：runtime 检查所有 capability 的 `success`，全部成功 → `job.completed`，任一失败 → `job.failed`

**Job 终态映射**：

| 所有 capability success | job 终态 |
|---|---|
| 全部 True | `job.completed` |
| 任一 False | `job.failed` |

**Setup 失败处理不同**：setup 失败 = job 立即失败，进入 preparation failure 路径，不进入 agent loop。

### 5.2 与其他概念的关系

| 概念 | 消费者 | 生命周期 | 事件责任 |
|---|---|---|---|
| Capability | Runtime 生命周期管理 | setup + finalize | 返回事件数据，runtime 代发 |
| Context Provider | LLM prompt 组装 | context 阶段一次性调用 | 否 |
| Tool | Agent Loop 中 LLM 调用 | per-call | 否（runtime 记录工具调用事件） |

### 5.3 Role 声明

Role 同时声明 capability 需求和 context provider 需求：

```python
metadata = RoleMetadata(
    name="worker",
    needs=["rcon_bridge", "script_sync"],           # capabilities
    contexts=["factorio_scripts", "task_history"],   # context providers
)
```

---

## 6. Observation 与演化闭环

详见 [ADR-0010](adr/0010-self-optimization-governance.md) 和 [ADR-0017](adr/0017-observation-unified-interface.md)。

### 6.1 Observation 分析

Job 达到终态后，Trenni 执行后置分析：

```
job.{completed, failed} → Trenni 查询 job 事件历史 →
遍历注册的 observation analyzer →
每个 analyzer 返回 observation 数据 →
Trenni 统一 emit observation.* 事件（携带 bundle + task_id + analyzer_version）
```

**触发条件**：Job 只有两个终态——`job.completed` 和 `job.failed`。两者都会触发 observation 分析。失败的 job 仍然有有价值的 observation 数据（如 retry pattern、budget variance）。

Observation analyzer 通过统一接口注册：

```python
class ObservationAnalyzer(Protocol):
    def analyze(self, job_events: list[Event]) -> list[ObservationData]: ...
```

默认 analyzer（budget_variance、tool_retry）和 bundle 提供的 analyzer 使用同一注册表，代码路径无区分。

### 6.4 Analyzer 版本定格

Observation 事件记录产生时的完整环境版本，用于历史追溯和复现：

```json
{
  "type": "observation.tool_retry",
  "data": {
    "bundle": "factorio",
    "task_id": "task-abc123",
    "analyzer_version": {
      "bundle_sha": "a1b2c3d",     // 分析时使用的 bundle commit sha
      "trenni_sha": "e4f5g6h",     // 分析时使用的 Trenni commit sha
      "palimpsest_sha": "f7g8h9i"  // 产生原始事件的 Palimpsest commit sha
    },
    ...  // 具体 observation 数据
  }
}
```

**三方 SHA 的职责**：

| SHA | 职责 |
|---|---|
| `bundle_sha` | bundle 提供的 analyzer 代码版本 |
| `trenni_sha` | Trenni（包含默认 analyzer）代码版本 |
| `palimpsest_sha` | 产生原始事件（`tool.called`、`llm.responded` 等）的 runtime 版本 |

**定格规则**：

1. **记录版本**：observation 事件必须携带完整的 `analyzer_version`，三方 SHA 都要记录
2. **应用时用最新**：Review task、optimizer task 应用 observation 数据时，默认使用当前版本
3. **复现时用定格**：如需严格复现（before/after 对比、问题诊断），可切换到事件中记录的版本

**版本选择时机**：

| 场景 | 版本 | 原因 |
|---|---|---|
| 常规优化循环 | 最新 | analyzer 改进应立即生效 |
| before/after 对比 | 定格 | 控制变量，排除 analyzer 变化影响 |
| 问题诊断/回溯 | 定格 | 复现当时的分析逻辑 |
| 研究/统计 | 可选 | 根据研究目的决定 |

### 6.5 累积触发的消费语义

累积触发按 bundle 分组计数，达到阈值后自动创建 Review Task。为保证原子性和幂等性，采用以下流程：

```
observation.* 累积达到 N 条 →
Trenni 选择 batch_members（本次触发的 observation event_id 列表）→
Trenni 创建 Review Task（spawn payload 携带 triggered_by = batch_members）→
Trenni emit observation.consumed（携带 batch_members + trigger_task_id）→
如果 emit 失败，下次重放时补发 consumed 事件
```

**原子性与幂等规则**：

1. **先创建 Review Task，再 emit consumed**：Review Task 创建是主动作，consumed 事件是因果记录
2. **以 triggered_by 为幂等键**：重放时检查是否已存在 Review Task 携带相同的 `triggered_by`
3. **已存在则仅补发 consumed**：如果 Review Task 已存在但 consumed 未发出，仅 emit consumed 事件
4. **不存在则重新创建**：如果 Review Task 不存在（上次创建失败），重新创建并 emit

**消费边界**：

| 字段 | 含义 |
|---|---|
| `batch_members` | 本次消费的 observation event_id 列表 |
| `trigger_task_id` | Review Task 的 task_id |
| `triggered_by` | Review Task spawn payload 携带的因果链 |

**Cooldown**：两次 Review Task 之间的最小时间间隔，防止短时间内连续触发。

```yaml
bundles:
  factorio:
    observation:
      accumulate: 20
      cooldown_minutes: 30
```

### 6.2 演化闭环

```
observation.* 事件 ──累积触发──→ Review Task ──产出──→ Improvement Proposal
                                                          │
                                                          ↓
                                                 普通优化 Task（修改 bundle repo）
                                                          │
                                                          ↓
                                                 下次 job 使用新代码 → 对比改善
```

- **累积触发**：Trenni 按 bundle 分组计数，N 条 observation 累积后自动创建 Review Task（默认 `accumulate: 20`）
- **优化是普通任务**：没有特殊的优化模式、没有特权访问、没有独立调度器
- **通过代码沉淀演化**：observation analyzer、capability、context provider、prompt 都是 bundle 中的代码，优化任务修改这些代码，修改就是 git commit

### 6.3 预算预测作为健康指标

Planner 的 `estimated_budget` 是预测值，不是执行约束。实际偏差作为系统健康度的代理指标。详见 [ADR-0004](adr/0004-budget-as-prediction.md)。

---

## 7. 编排与信息边界

### 7.1 Spawn 是唯一编排原语

系统没有预定义的 DAG 或工作流引擎。Task 调度层通过 `spawn()` 将 task 物化为 job DAG。任务分解决策属于 Planner 角色，不属于 Trenni。

### 7.2 字段归属

系统中的每个字段严格归属于三类之一：

1. **任务语义** (goal, repo, budget, eval_spec, bundle) — 由 Trigger 或 Spawn Payload 携带，存于 TaskRecord
2. **执行配置** (capabilities, contexts, tools, publication strategy) — 由 Bundle 中的 Role 定义派生，Spawn Payload 不可设置
3. **运行时身份** (job_id, resolved_ref, container_name) — 由 Trenni 在 Job 创建时机械分配

**Bundle 字段归属说明**：

- `bundle` 属于**任务语义**，由 Trigger 或 Spawn Payload 携带
- 如果 Trigger 未指定 bundle，Trenni 使用默认 bundle（通常为 `"default"`）
- Child task 的 bundle 默认继承父 task，但 spawn payload 可显式指定不同的 bundle
- Review task、optimizer task 通常继承触发信号的 bundle（保证优化闭环在同一 bundle 内）

**Repo 语义说明**：

- `repo` 在任务语义中指**任务目标仓库**（agent 要修改的代码仓库）
- 与 **Bundle Repo**（承载 bundle 内容的仓库）概念不同
- 避免混淆：文档中用 "bundle repo" 明确指 bundle 仓库，用 "repo" 或 "target repo" 指任务目标仓库

### 7.3 双层裁定

每个终结 Task 同时携带两个独立层次的结论：

- **结构裁定 (Structural Verdict)**：由 Trenni 根据 Job 终端状态确定性计算，不涉及 LLM，**始终存在**
- **语义裁定 (Semantic Verdict)**：由独立的 Eval Job 产出——对原始目标的质量判断（`pass / fail / unknown`），**可选**

详见 [ADR-0002](adr/0002-task-lifecycle-verdict.md)。

### 7.4 Publication 的三层职责分工

1. **变更存在性 gate（hallucination gate）**：`git diff --cached --quiet` 为真即 publication 失败。只回答"agent 是否真的改了文件"
2. **结构可接受性 gate（guardrail）**：bundle/role 声明的 publication-time 检查（Lua 语法、路径白名单等）
3. **目标达成语义判断**：由 evaluator role 在独立 job 中回答

(1)(2) 属于 git_workspace capability 的 finalize 内部逻辑；(3) 不在 finalization 链路上。

---

## 8. URI 合同

### 8.1 Scheme 集合

- `inline:` — 小数据直接在 event payload 中
- `file:///<path>` — 持久卷内裸文件
- `git+file://<path>@<ref>[#<subpath>]` — 本机仓库快照
- `git+ssh://<host>/<path>@<ref>[#<subpath>]` — 远端仓库快照（SSH）
- `git+https://<host>/<path>@<ref>[#<subpath>]` — 远端仓库快照（HTTPS）
- `http(s)://<host>/<path>` — 外部只读资源

### 8.2 约束

- `git+*` 的 `@<ref>` 必须是 commit sha 或 tag，**不允许**分支名（分支名非固定，破坏可复现性）
- `#<subpath>` 为可选，未指定时引用整个仓库快照
- Event Store 不解析 URI，不验证可达性

---

## 9. 术语速查

| 术语 | 定义 | 不是什么 |
|---|---|---|
| **Bundle** | 一类任务的可复用资产的逻辑身份 | 不是 URL、目录、git 仓库 |
| **Bundle Repo** | 承载 bundle 内容的独立 git 仓库 | 不是 monorepo 子目录、不是 submodule |
| **Bundle Source** | per-job 的运行时 bundle 描述 | 不是静态配置项 |
| **Bundle Registry** | Trenni 配置中按 name 键控的映射 | 不是中央 base 仓库、不存储 commit sha |
| **Workspace** | per-job 的 ephemeral clone | **永远不是权威** |
| **Capability** | bundle 提供的运行时服务管理单元（setup + finalize） | 不是代码库函数（lib）、有生命周期 |
| **Context Provider** | LLM 上下文的只读数据组装器 | 不发事件、无副作用 |
| **Tool** | Agent Loop 中可被 LLM 调用的操作 | 不管理基础设施生命周期 |
| **Artifact** | 被 event 引用的持久对象 | 不是存储模块记录、不是组件内部状态 |
| **Artifact URI** | 指向 artifact 的字符串引用 | 不是结构化对象，上下文由 event 字段提供 |
| **Content Authority** | URI scheme 背后负责字节持久化的系统 | 不是统一模块 |
| **Observation Analyzer** | 后置分析函数，返回 observation 数据 | 不直接 emit 事件 |
| **Event Store** | 系统的唯一因果权威（Pasloe 实现） | 不是内容存储、不解引用 URI |
| **Structural Verdict** | Trenni 根据 job.{completed, failed} 计算的 task 结果 | 不涉及 LLM |
| **Semantic Verdict** | Eval Job 产出的目标达成判断 | 可选的，不阻断 publication |
| **Hallucination Gate** | `git diff` 检查变更存在性 | 不做语义判断 |
| **Structural Guardrail** | bundle/role 声明的 publication-time 校验 | 不是 evaluator 的工作 |
| **Evolve Branch** | agent 演化使用的分支约定 | 不是强制约束 |
| **finalize.failed** | finalize 步骤失败的事件记录 | 携带诊断信息，不阻断事件流 |
| **observation.consumed** | observation 被触发消费的事件标记 | 携带 batch_members + trigger_task_id |
| **analyzer_version** | observation 产生时的环境版本 | bundle_sha + trenni_sha + palimpsest_sha（三方），用于复现 |
| **Bundle Workspace** | bundle repo 的 ephemeral clone | 用于加载代码，不是权威 |
| **Target Workspace** | 目标仓库的 ephemeral clone | 用于执行任务，不是权威 |
| **FinalizeResult** | capability finalize 的返回结构 | events + success 标志，决定 job 终态 |
