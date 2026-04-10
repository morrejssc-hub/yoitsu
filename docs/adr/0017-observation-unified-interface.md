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

Observation 分析在 job 完成后执行，而非 job 执行过程中实时触发。

流程：

```
job.completed 事件到达
→ Trenni 查询该 job 的事件历史
→ 遍历注册的 observation analyzer
→ 每个 analyzer 返回 observation 数据
→ Trenni 统一 emit observation.* 事件（携带 bundle + task_id）
```

**原因**：

- 有价值的信号（budget_variance、tool_retry 统计）本质上是聚合值，不需要实时
- 保持 Palimpsest 纯粹——只产出原始事件（`tool.called`、`llm.responded` 等），不做分析
- Trenni 已是事件消费者，后置分析步骤自然融入现有的 `_handle_job_done` 路径

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
