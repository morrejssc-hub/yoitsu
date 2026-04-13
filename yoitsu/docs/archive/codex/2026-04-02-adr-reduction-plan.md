# ADR 缩减与合并方案

日期：2026-04-02
状态：建议稿
目的：将现有 ADR 从“按历史讨论堆叠”压缩为“按当前代码边界和稳定结论组织”

## 1. 总原则

不是保留所有 ADR 再继续叠加，而是：

- 保留仍然稳定且独立的主题
- 合并已经互相覆盖的主题
- 将实现计划、review、探索性重构想法移出 ADR 主线
- 用少量、强边界的 ADR 代表当前真实系统设计

## 2. 建议保留为独立 ADR 的主题

### A. 系统分层与术语

保留来源：
- `0001-system-architecture.md`

保留内容：
- Pasloe / Trenni / Palimpsest / contracts 分层
- job 与 task 区别
- event-driven task lifecycle

建议动作：
- 重写为更短的系统基线 ADR
- 去掉已过期 roadmap 与未来态描述

### B. 任务/作业生命周期

保留来源：
- `0002-task-job-lifecycle.md`

保留内容：
- task state
- job terminal semantics
- structural / semantic verdict 的关系

建议动作：
- 保持独立
- 只删去与当前实现不一致的细枝末节

### C. 预算系统

保留来源：
- `0004-budget-system.md`

建议动作：
- 保持独立

### D. 治理与自优化

保留来源：
- `0010-self-optimization-governance.md`

建议动作：
- 保持独立

### E. Artifact Store

保留来源：
- `0013-artifact-store.md`

建议动作：
- 保持独立
- 作为新的基础设施 ADR

## 3. 建议合并的 ADR 主题

## 3.1 Runtime ADR

建议合并来源：

- `0003-runtime-execution.md`
- `0009-preparation-and-publication-functions.md`
- `0011-external-task-sources.md` 中与 Palimpsest runtime 直接相关的部分

合并后主题建议：

`Runtime Attempt Contract`

应包含：

- Palimpsest 是单次 attempt runtime
- 四阶段保留：preparation / context / interaction / publication
- `RuntimeContext`
- team-aware runtime resolution 的最小必要部分
- artifact store 如何进入 runtime（只写运行时接口，不重复物理层）
- `git_ref` 的兼容地位

不应包含：

- 过强的“事件驱动内核替代四阶段”设想
- 过度前瞻的 attempt type explosion

## 3.2 Task/Spawn/Intake ADR

建议合并来源：

- `0007-task-job-boundary.md`
- `0008-task-creation-and-ingestion.md`

合并后主题建议：

`Task Semantics And Spawn Contract`

应包含：

- task semantics / execution config / runtime identity 的分类
- spawn payload 边界
- goal / budget / repo / team 的权威来源
- trigger -> task -> job 的入口路径

## 3.3 Team/External Domain ADR

建议合并来源：

- `0011-external-task-sources.md`
- `0012-factorio-task-source.md`

合并后主题建议：

拆成两个层次：

1. `Team As Runtime Isolation Boundary`
2. `Factorio Domain Integration`

理由：
- `0011` 其实是通用基础设施
- `0012` 是具体任务域
- 两者不该继续缠在一起

其中：
- 通用 team/runtime 规则保留
- Factorio 要按新的 artifact store 语义重写，不能继续沿用旧的 git/workspace 中心假设

## 4. 建议降级出 ADR 主线的文档

以下文档不应再承担“当前系统规范”的职责：

- `docs/architecture.md`
  - 由新的合并架构文档替代
- `docs/event-artifact-runtime-redesign.md`
  - 保留为重构讨论记录
- `docs/notes/...`
  - 保留为探索记录
- `docs/plans/...`
  - 保留为实施计划
- `docs/reviews/...`
  - 保留为 review 历史
- `docs/superpowers/...`
  - 保留为历史设计素材，不作为现行规范

## 5. 建议形成的新 ADR 集

建议最终压缩到下面这组主 ADR：

1. `System Architecture And Terms`
2. `Task And Job Lifecycle`
3. `Runtime Attempt Contract`
4. `Task Semantics And Spawn Contract`
5. `Budget System`
6. `Task-Level Publication` 或并入 Runtime/Task Contract
7. `Self-Optimization Governance`
8. `Team As Runtime Isolation Boundary`
9. `Artifact Store`
10. `Factorio Domain Integration`

这已经足够覆盖当前主线，不需要再保留十几份高度交叠的系统 ADR。

## 6. 重写顺序建议

按收益和依赖关系，建议顺序如下：

1. 先写合并后的系统总文档
2. 再重写 `Runtime Attempt Contract`
3. 再重写 `Task Semantics And Spawn Contract`
4. 再把 `0011/0012` 拆开重写
5. 最后处理是否保留 `0006` 为独立 ADR

## 7. 对 `0006` 的处理建议

`ADR-0006: task-level publication` 现在处在中间地带。

建议暂时不要删，但也不要继续把它当主线文档。
等新的 runtime/publication 设计稳定后，再决定：

- 是否并入 `Runtime Attempt Contract`
- 还是保留为单独的“外部协作输出” ADR

## 8. 结论

当前文档整理的目标不应是“把旧文档重新摆整齐”，而应是：

- 用一份新的系统总文档替代散乱的系统描述
- 用更少、更强边界的 ADR 替代历史叠加的 ADR 集
- 把实现计划、review、探索记录明确降级为旁系材料

这份方案对应的结果就是：

- 新的合并架构设计：见同目录 `2026-04-02-merged-architecture.md`
- 新的 ADR 主线：按本文方案逐步收缩与重写
