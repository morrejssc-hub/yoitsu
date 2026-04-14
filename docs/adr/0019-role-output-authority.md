# 0019: Role Output Authority

- Status: Suspended (2026-04-14)
- Superseded by: ADR-0021
- Related: ADR-0015, ADR-0016

> **Suspended note (2026-04-14)**
>
> 本 ADR 的表述把 "role 的输出权威归属" 与 "runner 的工作区路由" 绑在同一个字段上，
> 与 "event store 是唯一真实来源"（见 ADR-0020）在概念上冲突。实现上 `output_authority`
> 只影响 runner 选择 cwd，并不承担真值模型职责。
>
> 该问题在 ADR-0021 中以 "capability surface（装饰器）+ bundle trust ref（git）" 的正交
> 二分重新解决：执行表面由 surface 决定，信任边界由 ref 决定，真值仍由事件独占承担。
>
> 本 ADR 暂停生效：`output_authority` 字段在 role metadata 中保留但不再承载语义，
> 工作区路由与控制面准备改由 ADR-0021 的机制承接。下列原文仅作为讨论背景保留，
> 不再作为架构决策被引用。

---

## 1. 现状与存在的问题

当前系统中，部分 role 同时混合了两种完全不同的输出语义：

1. **仓库型输出**：在 target workspace 中修改文件，并通过正式 publication 路径把结果持久化到远端仓库。
2. **运行时型输出**：直接改变 live runtime、外部服务或共享世界状态。

这两类语义被混在同一个 role 或同一类 smoke test 中，会造成四个问题：

1. **权威来源不清楚**：一个 job“成功”时，无法立刻判断成功落在仓库、临时 workspace、side clone，还是 live runtime。
2. **评估标准互相污染**：repo evaluator 和 runtime evaluator 关注的是不同事实，但当前很容易被迫共用一套“文件是否存在/目标是否达成”的混合标准。
3. **手工 side clone 会制造伪成功**：agent 在另一个临时 clone 或非权威路径里完成修改，并不等于系统获得了权威产物。
4. **Smoke test 含义失真**：一个本来要验证“repo 发布”的 smoke test，如果使用了 runtime role 或混合语义 role，测试通过或失败都无法给出清晰结论。

## 2. 做出的决策与原因

### 2a. 每个 role 只允许一个输出权威

每个 role 必须属于以下三类之一：

1. **Repository-authoring role**：其有效输出是仓库中的持久化结果
2. **Live-runtime role**：其有效输出是外部运行时或共享世界状态的改变
3. **Read-only / analysis role**：其职责是读取、判断、规划，不生成新的权威输出

单个 role 不允许同时承担 repository-authoring 与 live-runtime 两种权威输出。

**原因**：只有先固定“哪一个系统对这个 role 的产物负责”，后续 publication、evaluation、smoke 才有一致语义。

### 2b. Repository-authoring role 的唯一权威是目标仓库

当一个 role 被定义为 repository-authoring role 时：

- 它的有效修改必须落在 runtime 提供的目标 workspace 所代表的权威仓库上
- 它的持久化必须经过正式的 publication capability
- 任何 side clone、额外 checkout、临时目录中的修改都不构成权威输出

**原因**：只要允许多个“差不多也算结果”的写入路径，repo publication 就无法被审计，也无法被 evaluator 和上游任务稳定消费。

### 2c. Live-runtime role 的成功不等于仓库发布

当一个 role 被定义为 live-runtime role 时，它可以改变外部系统状态，但这种成功不应被解释为“代码/仓库结果已经发布”。

如果某个 bundle 同时需要“先修改仓库中的脚本/配置，再让 live runtime 生效”，这必须拆成两个语义明确的 role 或任务阶段，而不是由一个 role 混合完成。

**原因**：运行时生效与仓库持久化是两种不同权威；把它们塞进同一角色只会让故障无法归因。

### 2d. Evaluator 必须服从被评估对象的权威边界

Evaluator 必须是 authority-aware 的：

- repository evaluator 只判断仓库产物与交付语义
- live-runtime evaluator 只判断外部系统状态与行为语义
- planner / join logic 可以综合两者，但不应让单个 evaluator 同时承担两种权威的底层事实判断

**原因**：把“仓库里是否真的有产物”和“运行时是否真的生效”混成一个 evaluator，会让失败原因不可分解。

### 2e. Smoke test 按 authority 分类，而不是按 bundle 名称分类

Smoke test 至少分为三类：

1. **Repository smoke**：验证 workspace 写入、publication、权威仓库可见性
2. **Live-runtime smoke**：验证 capability、连接、同步、外部系统效果
3. **Planning/analysis smoke**：验证无副作用 role 的推理与调度行为

一个 smoke test 不得同时承担多种 authority 的验收目标。

**原因**：Smoke 的价值来自于失败结论足够单一。混合 authority 的 smoke 只会制造“到底哪层坏了”的噪音。

### 2f. Planner 可以跨 authority 编排，但不能抹平 authority 边界

Planner 可以创建 repository-authoring child、live-runtime child 和 evaluator child，并在 join 阶段综合它们的结果；但 planner 不得把“跨 authority 的完整闭环”压扁成一个语义模糊的 child role。

**原因**：编排层负责组合，执行层负责单一权威。边界必须保持清晰。

## 3. 期望达到的结果

- 每个 role 的成功语义都可以用一句话说明“它对哪个系统负责”
- repo 发布问题与 live runtime 问题可以被独立定位
- evaluator 结果更容易解释，也更容易被 planner 组合
- smoke test 的通过/失败重新具备明确诊断价值

## 4. 容易混淆的概念

- **文件存在于某处** 不等于 **仓库权威输出成立**
  - 只有权威仓库上的正式结果才算 repository-authoring role 的产物

- **运行时生效** 不等于 **代码已发布**
  - live runtime 可以成功，仓库仍然没有对应持久化结果

- **Planner 能看见两边结果** 不等于 **Child role 可以混合两边职责**
  - 综合判断属于 planner
  - 单一输出权威属于具体执行 role

## 5. 对之前 ADR 或文档的修正说明

- ADR-0015 中“workspace 不是权威”的表述继续有效；本 ADR 进一步规定，side clone 或任意非权威路径也不应被当作结果。
- ADR-0016 中 capability 负责 lifecycle、context 负责信息组装的边界继续有效；本 ADR 补充的是“role 的结果最终归属于哪个权威系统”。
- ADR-0012 中与 Factorio 相关的 role 语义，需要在后续 bundle 文档中重新按 repository-authoring 与 live-runtime 边界重述，而不再允许“写脚本并立即作用于 live world”被视为同一种输出。
