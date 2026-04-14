# 0020: Reconciled Job Terminal State

- Status: Proposed
- Related: ADR-0002, ADR-0016, ADR-0017

## 1. 现状与存在的问题

当前 job 在观察层面存在三个互相独立但会被操作者混读的信号来源：

1. **agent 生命周期事件**：反映 agent loop 自身是否结束、给出了什么 summary
2. **runtime / finalize 结果**：反映 capability 是否真正完成持久化或清理语义
3. **supervisor 生命周期事件**：反映容器、进程和实际执行环境是否完成了一个可接受的 job 生命周期

如果操作界面或历史投影只暴露其中一层，就会产生“看起来 completed，实际上 runtime 或 supervisor 已失败”的假象。这会直接误导 smoke test 诊断、bundle 调试和系统治理。

## 2. 做出的决策与原因

### 2a. Canonical terminal truth 是对多层终态的统一解释

Job 的规范性终态不是某一条单独事件，而是以下三层事实的统一解释：

1. agent 是否完成了自己的工作回合
2. runtime/finalize 是否确认了所需持久化与生命周期收尾
3. supervisor 是否确认执行环境完成了一个有效 job

只要任一层给出不可接受的失败信号，job 就不能被解释为“成功完成”。

**原因**：job 是一个跨 agent、runtime、supervisor 的复合过程。任何单层“completed”都不足以单独代表完整成功。

### 2b. 投影是便利视图，不是权威定义

`/jobs`、TUI、日志摘要、监控面板都只是 event store 的投影视图。任何投影都可以为了可读性省略信息，但不得重新定义 job 终态语义。

如果某个投影没有展示 runtime 或 supervisor 层的失败，它的结论必须被视为“可能不完整”，而不是“权威真实”。

**原因**：投影的职责是阅读便利，不是替代因果记录。

### 2c. 文本 summary 不能作为终态证据

agent summary、planner 叙述、report 摘要可以作为线索，但不能作为“工具是否调用”“产物是否发布”“job 是否真正成功”的证据来源。

这些问题必须回到对应的事件层事实来判断。

**原因**：summary 是模型叙述，event 才是系统因果记录。

### 2d. 调试与验收必须同时看三类证据

对 job 执行问题的诊断和验收，至少需要同时考虑：

1. agent 的实际动作证据
2. finalize / publication 的结果证据
3. supervisor 的执行环境证据

任何只依赖单一层视图的结论，都应被视为初步判断，而不是根因结论。

**原因**：如果诊断流程本身忽略某一层，系统就会反复把投影视图误当成真实源。

### 2e. Event store 继续作为时序与因果权威

对 job 终态的最终解释权仍属于 event store 中的时序记录，而不是任何单独的 API projection、面板字段或自由文本。

**原因**：ADR-0015 和 ADR-0017 已经把 event store 确立为时序与分析的权威来源。本 ADR 只是把这一原则明确延伸到 job 终态解释。

## 3. 期望达到的结果

- 操作者不会再把单一层的 `completed` 误读为完整成功
- smoke test 报告可以明确区分“agent 完成了什么”和“系统最终接受了什么”
- 投影层即使做裁剪，也不会继续制造概念性误导

## 4. 容易混淆的概念

- **Agent 完成** 不等于 **Job 成功**
  - agent 只代表模型回合结束
  - job 成功还要求 runtime 与 supervisor 层都可接受

- **投影缺失失败信息** 不等于 **失败不存在**
  - 这只说明视图不完整

- **Summary 说做了** 不等于 **系统事实发生了**
  - 是否调用工具、是否持久化、是否被 supervisor 接受，必须看事件

## 5. 对之前 ADR 或文档的修正说明

- ADR-0002 关于 job/task 生命周期的讨论，需要在后续文档修订中补上“终态解释是多层统一结果”的视角，而不是只看 agent 发出的 terminal event。
- ADR-0016 中 capability `success` 决定 job 终态的原则继续有效；本 ADR 补充的是，这个原则仍处在 supervisor 执行环境约束之内。
- ADR-0017 中 event store 作为分析权威的原则，扩展到 job 终态解释与调试流程本身。
