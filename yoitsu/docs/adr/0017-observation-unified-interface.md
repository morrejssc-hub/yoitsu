# 0017: Observation 统一分析接口

## 1. 现状与存在的问题

ADR-0010 确立了自优化闭环的治理哲学，但观察信号的来源和触发方式存在两个问题：

1. **信号类型预定义不可持续**：当前的 `observation.budget_variance`、`observation.tool_retry` 等信号硬编码在 Trenni 和 Palimpsest 中。新的 bundle（如 Factorio）需要 bundle-specific 的观察信号（RCON 超时、脚本错误），但没有标准的扩展机制。
2. **信号发送分散**：部分信号从 Palimpsest 内部实时发出，部分从 Trenni 侧后置计算。发送责任分散导致 bundle 代码需要了解事件系统细节。

## 2. 做出的决策与原因

### 2a. Observation Analyzer 统一接口

所有 observation 分析通过统一接口实现：

```python
class ObservationAnalyzer(Protocol):
    def analyze(self, job_events: list[Event]) -> list[ObservationData]: ...
```

- Analyzer 只返回结构化数据，不直接 emit 事件
- Trenni 统一 emit observation 事件

**原因**：与 capability 的原则一致——组件只关心做什么和回答做了什么，事件发送是系统级关注点。

### 2b. 默认与 bundle 提供的 analyzer 无区分

默认 analyzer（budget_variance、tool_retry）和 bundle 提供的 analyzer 使用同一注册表、同一代码路径。默认的只是恰好预注册在 Trenni 包中。

Bundle 通过 Trenni 注册，其 `observations/` 目录中的 analyzer 也随注册过程一同加载。

**原因**：特殊通道引入复杂性和测试盲区。统一注册让默认 analyzer 也可以被 bundle 覆盖或禁用。

### 2c. Trenni 后置分析，非实时

Observation 分析在 job 达到终态后执行，而非 job 执行过程中实时触发。

**流程**：

```
job.{completed, failed} 事件到达
→ Trenni 查询该 job 的事件历史
→ 遍历注册的 observation analyzer
→ 每个 analyzer 返回 observation 数据
→ Trenni 统一 emit observation.* 事件（携带 bundle + task_id + analyzer_version）
```

**触发条件**：Job 只有两个终态（`job.completed` 和 `job.failed`），两者都会触发分析。失败的 job 仍然有有价值的 observation 数据——`job.failed` 的 retry pattern、budget variance 都是优化信号来源。

> **注意**：`partial`、`cancelled`、`eval_failed` 是 **Task** 状态，不是 Job 状态。见 ADR-0002 §2a Task 状态机。

**原因**：

- 有价值的信号（budget_variance、tool_retry 统计）本质上是聚合值，不需要实时
- 保持 Palimpsest 纯粹——只产出原始事件（`tool.called`、`llm.responded` 等），不做分析
- Trenni 已是事件消费者，后置分析步骤自然融入现有的 job terminal 路径

### 2d. Observation 按 bundle + task 分组

Observation 事件携带 `bundle` 和 `task_id`。累积触发规则按 bundle 分组计数，而非全局混合。

**原因**：不同 bundle 的信号阈值和优化周期不同。Factorio 的 RCON 超时信号与 webdev 的 tool retry 信号混在一起计数没有意义。

### 2e. Observation Analyzer 可演化

Bundle 提供的 analyzer 作为 bundle repo 中的代码（`observations/` 目录）随 bundle 演化。优化任务可以添加新的 analyzer 或修改阈值。

**原因**："通过代码沉淀演化"——observation analyzer 是代码，每次改进是 git commit，可追溯、可回滚。这与其他架构通过 skill 沉淀演化不同，Yoitsu 通过代码来沉淀演化。

### 2f. 累积触发语义

Trenni 的 Trigger 规则在 N 条匹配的 observation 事件累积后自动创建 Review Task（默认 `accumulate: 20`）。

这是一个简单的批处理模式：

- 按 bundle 分组计数
- 达到阈值后创建 Review Task
- Review Task 由 optimizer role 执行：读取近期 observation 事件，识别重复模式，产出具体的改进提案
- 每个提案成为独立的优化 Task，通过正常 spawn 执行
- 优化 Task 修改 bundle repo 中的代码（capability、context provider、prompt、observation analyzer 等）

### 2g. Analyzer 版本定格

Observation 事件记录产生时的完整环境版本，包含三方 SHA：

```json
{
  "type": "observation.tool_retry",
  "data": {
    "bundle": "factorio",
    "task_id": "task-abc123",
    "analyzer_version": {
      "bundle_sha": "a1b2c3d",     // bundle 提供的 analyzer 代码版本
      "trenni_sha": "e4f5g6h",     // Trenni（包含默认 analyzer）版本
      "palimpsest_sha": "f7g8h9i"  // 产生原始事件的 runtime 版本
    },
    "tool": "call_script",
    "retry_count": 3
  }
}
```

**三方 SHA 的职责**：

| SHA | 职责 |
|---|---|
| `bundle_sha` | bundle 提供的 analyzer 代码版本 |
| `trenni_sha` | Trenni（包含默认 analyzer）代码版本 |
| `palimpsest_sha` | 产生原始事件的 runtime 版本 |

**定格原则**：

1. **记录必须**：每条 observation 事件必须携带完整的 `analyzer_version`，三方 SHA 都要记录
2. **应用默认最新**：Review/optimizer task 默认使用当前版本，让改进立即生效
3. **复现用定格**：before/after 对比、问题诊断需排除 analyzer 变化影响时，可切换到事件记录的版本

这保证了 observation 数据的**可追溯性**（完整版本记录）和**可演化性**（应用最新）。

### 2h. 累积触发的消费语义

为保证原子性和幂等性，采用以下流程：

**触发流程（先创建 Task，再 emit consumed）**：

```
N 条 observation 累积 →
Trenni 选择 batch_members（observation event_id 列表）→
Trenni 创建 Review Task（spawn payload 携带 triggered_by = batch_members）→
Trenni emit observation.consumed（携带 batch_members + trigger_task_id）→
如果 emit 失败，下次重放时补发 consumed 事件
```

**原子性与幂等规则**：

1. **先创建 Review Task，再 emit consumed**：Review Task 创建是主动作，consumed 事件是因果记录
2. **以 triggered_by 为幂等键**：重放时检查是否已存在 Review Task 携带相同的 `triggered_by`
3. **已存在则仅补发 consumed**：如果 Review Task 已存在但 consumed 未发出，仅 emit consumed 事件
4. **不存在则重新创建**：如果 Review Task 不存在（上次创建失败），重新创建并 emit

**去重实现**：

- 不依赖额外 cursor 持久化
- 通过查询 Review Task 的 `triggered_by` 字段实现幂等
- `observation.consumed` 事件是因果记录，不是去重依据

**Cooldown**：建议配置 `cooldown_minutes`，防止短时间内连续触发。

### 2i. Observation Analyzer 注册时机

Analyzer 随 bundle 注册加载：

- **Trenni 启动时**：遍历 registry 中所有 bundle，加载每个 bundle 的 `observations/` 目录
- **Bundle 更新后**：如果 bundle repo 的 evolve 分支添加了新 analyzer，下次 Trenni 重启或显式 reload 时生效
- **Per-job 版本定格**：分析某 job 时，使用该 job 的 `resolved_ref` 对应的 bundle 版本中的 analyzer

第三点保证了**可复现性**：同一个 job 的事件历史，用同一个 analyzer 版本分析，得到相同结果。

**analyzer_version 记录**（见 §2g）：每条 observation 事件携带三方 SHA（bundle_sha + trenni_sha + palimpsest_sha），完整记录分析环境版本。

## 3. 期望达到的结果

- Observation 分析有标准扩展机制，bundle 可以提供自定义 analyzer
- 事件发送统一由 Trenni 代理，bundle 代码无需了解事件系统
- 信号类型可随 bundle 演化，不需要核心系统变更

## 4. 容易混淆的概念

- **Observation Analyzer vs Evaluator**
  - Analyzer 是确定性的后置分析（tool retry 了 3 次、budget 偏差 40%），不涉及 LLM
  - Evaluator 是 LLM 驱动的语义判断（目标是否达成），作为独立 job 运行

- **Observation 信号 vs Event**
  - Event 是 Palimpsest 执行过程中产生的原始记录（`tool.called`、`llm.responded`）
  - Observation 是 Trenni 对这些原始事件的后置分析产出

- **Observation Analyzer vs Capability**
  - Analyzer 运行在 Trenni 侧，job 完成后执行
  - Capability 运行在 Palimpsest 侧，job 执行过程中活跃
  - 两者都遵循"返回数据、宿主代发事件"的原则

## 5. 对之前 ADR 或文档的修正说明

- 本 ADR 补充 ADR-0010 §2b 的信号触发机制。ADR-0010 的累积触发语义不变，但信号来源从"Trenni 和工具网关按确定性条件机械发出"变为"通过统一 analyzer 接口后置分析产出"。
- ADR-0010 中"Phase 1-2：在相关代码路径中发出信号"不再是 Palimpsest 内的实时发出，而是通过 Trenni 注册的 analyzer 后置产出。
- ADR-0015 §2.3 的 bundle 目录结构新增 `observations/` 目录。
