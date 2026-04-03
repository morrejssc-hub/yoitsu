# Yoitsu 架构重设计

Date: 2026-03-24

## 一、现状问题

### 1.1 Job 和 Task 未分离

当前 job 同时承载执行语义和业务语义。`task_complete(status="partial")` 混淆了「pipeline 是否正常执行」和「工作是否完成」两个维度。spawn 后 parent job 无法自然结束——它不是失败，也不算完成。

### 1.2 组件间 Contract 全部隐式

Palimpsest 用 Pydantic model 构造事件，Trenni 用 `dict.get()` 解析。JobConfig 在 Trenni 中是 untyped dict，在 Palimpsest 中是 typed dataclass。Git 认证逻辑在三处重复。任意一侧的字段变更都可能静默破坏另一侧。

### 1.3 Supervisor 是单体

`supervisor.py` 793 行，承担事件轮询、事件路由、幂等去重、任务入队、spawn 解析、依赖追踪、replay、checkpoint/reap、容量管理、进程生命周期 10 类职责，管理 10 个可变状态集合。

### 1.4 Trenni 直接绑定 Podman

Supervisor 直接引用 `PodmanBackend`，没有抽象的 Isolation Backend 接口。从调度到容器的路径缺少中间抽象层。

### 1.5 Fork-Join 不完整

只有 fan-out，没有 join。Continuation 在 ADR-0004 中被暂停。

### 1.6 Evo 死代码

3/22 评审标记为 P0 的死代码（类模式文件、无效 YAML）仍未清理。

---

## 二、设计决策

### 2.1 Job / Task 分离

**Job** 是底层执行单元。它运行一个 Palimpsest pipeline，结果是**二值的**：success 或 failure。Success 意味着 pipeline 正常执行完毕（四阶段都成功了，尤其是最后一个阶段），failure 意味着运行时出了问题（crash、timeout、runtime constraint violation）。

**Task** 是逻辑工作单元。一个 task 可能由多个 job 完成。Task 可以有中间状态（in_progress、blocked、needs_review）。Task 的完成由 job 中的 Agent 通过 `task_complete` 事件声明。

| | Job | Task |
|---|---|---|
| 结果 | success / failure | 由 Agent 声明（complete / failed / in_progress） |
| 生命周期 | Palimpsest pipeline 的一次执行 | 从 `task.submit` 到最终被 Agent 标记完成 |
| 一对多 | 一个 task 可以由多个 job 完成 | — |
| 归属 | Trenni (Scheduler + Isolation) + Palimpsest (Runtime) | 事件流 (Pasloe) + Scheduler 监护 |

`task_complete` 不再与 job 终止强绑定。它是 Agent 发射的事件，表达「这项工作已经完成」。Job 层面的结束信号（告诉 runtime 停止 interaction loop）独立于 task 状态。

当前的 `status="partial"` 消失。Job 要么成功要么失败。如果 Agent 做了一部分工作但还没做完（需要 spawn 子任务），parent job 正常 success，task 仍然 in_progress。

---

### 2.2 条件化 Spawn —— 唯一编排原语

Spawn 是唯一的编排原语。任何复杂的 DAG 通过递归 spawn 实现。

#### Job 调度条件模型

每个 job 携带一个**条件表达式** (`Condition`)，加上队列位次和 slot 可用性，共同决定是否启动。

条件表达式是一棵组合树，由四种节点构成：

```python
Condition = TaskIs | All | Any | Not

TaskIs(task_id, result)   # 叶节点: 某 task 达到了某状态
All([...])                # 所有子条件满足
Any([...])                # 任一子条件满足
Not(child)                # 取反
```

采用三值求值: `True`（已满足）/ `False`（已不可能满足 → 取消此 job）/ `None`（尚不确定 → 继续等待）。Scheduler 每当有 job 状态变更时，对所有 pending job 求值一次。

#### Spawn 展开

Agent 调用 `spawn(tasks=[T1, T2, T3], on_fail="cancel_siblings")`，spawn handler 将其展开为 **N+1 个带条件的 job**：

| Job | Condition |
|---|---|
| job_1 (T1) | `Not(Any([TaskIs(T2, failure), TaskIs(T3, failure)]))` |
| job_2 (T2) | `Not(Any([TaskIs(T1, failure), TaskIs(T3, failure)]))` |
| job_3 (T3) | `Not(Any([TaskIs(T1, failure), TaskIs(T2, failure)]))` |
| job_join | `All([TaskIs(T1, terminal), TaskIs(T2, terminal), TaskIs(T3, terminal)])` |

Agent 通过 `spawn()` 工具声明意图，spawn handler 负责将意图翻译为 per-job 的条件表达式。Scheduler 不理解 spawn 语义——它只求值条件。

不同策略对应不同的条件组合：

| 策略 | Children 条件 | Join 条件 |
|---|---|---|
| 全部完成再 join | 无条件 | `All(每个 child terminal)` |
| 任一失败取消 siblings | `Not(Any(sibling failure))` | `All(每个 child terminal)` |
| 任一成功即 join | `Not(Any(sibling success))` | `Any(任一 child success)` |

#### Join Job

Join job 是一个普通 job。它的 Role 指定了一个特殊的 context provider，该 provider 做两件事：

1. 从 Pasloe 查询 parent job 的 `agent.*` 事件 → 重建 parent 的 messages 历史
2. 从 Pasloe 查询 sibling jobs 的 `job.completed` / `job.failed` 事件 → 获取 children 结果

对 Palimpsest runtime 没有任何特殊机制——它看到的就是一个正常 job，只是 context 比普通 job 丰富。Context provider 本身是 evo 的一部分，可演化。

#### 递归编排

复杂编排通过递归实现。如果 T2 需要进一步分解，它在执行时再调用 spawn——Scheduler 对它的处理方式完全相同。Follow-up（分支闭环、审计等）可以被包裹在 task 下由多个 job 完成。每个 job 看到的世界一致：从哪里来、什么任务、结果放到哪里。

---

### 2.3 三层抽象

从「接到一个任务」到「Agent 开始工作」，经过三层，每层有明确的承诺：

| 层 | 归属 | 承诺 | 不关心 |
|---|---|---|---|
| **Scheduler** | Trenni | 容量控制、条件检查、task 推进监护 | 怎么启动、在哪运行 |
| **Isolation Backend** | Trenni (Protocol) | 环境准备（env 注入）、进程隔离、生命周期管理 | 任务内容、调度顺序 |
| **Runtime** | Palimpsest | 4-stage pipeline、LLM 交互、工具执行、事件发射 | 谁调度了它、它在什么容器里 |

Isolation Backend 是 Protocol：

```python
class IsolationBackend(Protocol):
    async def prepare(self, spec: JobRuntimeSpec) -> JobHandle: ...
    async def start(self, handle: JobHandle) -> None: ...
    async def inspect(self, handle: JobHandle) -> ContainerState: ...
    async def stop(self, handle: JobHandle, grace: int) -> None: ...
    async def remove(self, handle: JobHandle, force: bool) -> None: ...
    async def logs(self, handle: JobHandle) -> str: ...
```

`PodmanBackend` 是当前唯一实现。未来可能有 `SubprocessBackend`（开发）、`KubernetesBackend`（生产）。

Scheduler 维护 task 生命周期：确保 task 能推进下去，卡住时向上反馈。Job 层面处理 task 逻辑：成功还是失败，需要分解还是直接执行。

**环境注入是 Isolation Backend 的统一职责。** 所有从 Trenni 传递给 Palimpsest 的运行时依赖（job config、API keys、git credentials、git identity）都通过 `prepare()` 注入为环境变量。

---

### 2.4 共享 Contract 仓库 (`yoitsu-contracts`)

独立仓库，避免循环依赖。

```
yoitsu-contracts/
  src/yoitsu_contracts/
    events/           # 所有事件类型的 Pydantic models
    config/           # JobConfig 完整类型定义
    client/           # PasloeClient (async) + EventEmitter (sync)
    env/              # git_auth 等环境注入工具
```

**依赖方向**：Palimpsest → contracts，Trenni → contracts，Yoitsu CLI → contracts。Pasloe 不依赖 contracts（保持 schema-agnostic）。

当前 Palimpsest 的 `EventEmitter` (sync httpx) 和 Trenni 的 `PasloeClient` (async httpx) 有大量重复（auth header、error handling），统一后只维护一份。

---

### 2.5 Trenni 模块拆分

```
trenni/trenni/
  supervisor.py        # 入口: start/stop + run_loop + event 路由
  state.py             # SupervisorState dataclass (收敛所有可变集合)
  scheduler.py         # ready_queue + drain + capacity + 条件检查 + task 推进
  spawn_handler.py     # 解析 spawn event → N+1 conditional jobs
  replay.py            # 从事件流重建 SupervisorState
  checkpoint.py        # 定期 checkpoint + reap
  isolation.py         # IsolationBackend Protocol + env 注入
  podman_backend.py    # Podman 实现 (已存在)
```

核心思路是引入 `SupervisorState`，将 10 个散布的可变集合收敛为一个对象。Replay 变成 `SupervisorState.rebuild_from_events()`，checkpoint 变成 `state.snapshot()`，新功能只需扩展 state，不影响主循环。

---

### 2.6 Evo 清理

删除所有死代码：

- `contexts/file_tree_provider.py`、`task_description_provider.py`、`recent_events_provider.py`、`version_history_provider.py`
- `contexts/default.yaml`
- `tools/file_ops.py`

只保留装饰器模式实现。

---

### 2.7 architecture.md 与实际对齐

| 文档声明 | 实际状态 | 行动 |
|---|---|---|
| Dual Gate Validation | 均未实现 | 显式标注为 Phase 4/5 |
| Supervisor detects changed_files violations | 未实现 | 移入 Roadmap |
| Fork-Join 作为唯一编排原语 | 条件化 spawn + join job | 按新设计更新 |
| Three-layer permissions enforced by Supervisor | 无检测代码 | 改为 enforced by convention |
