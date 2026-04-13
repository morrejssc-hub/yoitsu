# Yoitsu System Plan

日期：2026-04-10
状态：文档层架构重构完成，跨文档一致性已清理，进入代码落地阶段
范围：`yoitsu` / `yoitsu-contracts` / `trenni` / `palimpsest` / `pasloe`

## 1. 当前基线

已完成能力：

- canonical contract、runtime hardening、observation loop、external trigger、artifact runtime 均已落地
- 非 Git 任务已具备 artifact 输入/输出主链路
- GitHub 上下文、reviewer、PR 工具、外部触发入口已具备基本能力
- Phase 1 Autonomous Review Loop 端到端闭环验证通过

文档层架构重构（2026-04-10 第三轮完成）：

- `architecture.md` 关键结构问题解决：
  - §3.3.1: 新增 Target Source 概念，与 Bundle Source 分离
  - §5.1/§5.4: Finalize 返回 FinalizeResult(events, success)，job 终态由 success 决定
  - §6.4: analyzer_version 三方 SHA（bundle_sha + trenni_sha + palimpsest_sha）
  - §6.5: 累积触发原子性（先创建 Task，再 emit consumed，triggered_by 幂等）
- [ADR-0016](docs/adr/0016-capability-model.md) 补充 2f: finalize 返回 FinalizeResult(events, success)
- [ADR-0017](docs/adr/0017-observation-unified-interface.md) 补充 2g/2h: 三方 SHA 版本定格、原子性消费语义
- [ADR-0012](docs/adr/0012-factorio-task-source.md) 补充 D3: Target Source 与 Bundle Source 分离，artifact URI 指向远端
- [ADR-0010](docs/adr/0010-self-optimization-governance.md) 清理旧 observation 模型表述
- [ADR-0015](docs/adr/0015-bundle-as-repo.md) §6 Push 策略拍板（success 标志决定终态、artifact URI 指向远端）

旧版 ADR-0012 移入 `docs/archive/adr/0012-factorio-task-source-old.md`

## 2. 架构核心共识

1. **Event Store 为唯一因果权威**，不对内容可用性负责
2. **Artifact 为 first-class 概念**：身份(URI) + 因果(Event) + 可用性(Content Authority)
3. **Runtime 四阶段流水线**：preparation → context → agent loop → finalization
4. **Capability 模型**：setup + finalize，返回事件数据，runtime 代发，capability 间无排序
5. **Context fn 独立于 capability**：只读数据组装，服务 LLM prompt
6. **Task/Job 调度分离**：spawn 事件即边界，task 层将 task 物化为 job DAG
7. **Observation 统一接口**：Trenni 后置分析，默认和 bundle 提供的 analyzer 无区分，按 bundle/task 分组
8. **通过代码沉淀演化**：observation analyzer、capability、context provider、prompt 都是 bundle 中可演化的代码
9. **Finalize 返回 success 标志**：每个 capability 返回 FinalizeResult(events, success)，内部重试，runtime 根据 success 决定 job 终态
10. **Observation 版本定格**：事件记录三方 analyzer_version（bundle_sha + trenni_sha + palimpsest_sha）
11. **累积触发原子性**：先创建 Review Task，再 emit consumed，以 triggered_by 幂等
12. **Workspace 双轨**：BundleSource.workspace 加载代码，TargetSource.workspace 执行任务
13. **Artifact URI 指向远端**：不能指向 ephemeral workspace 路径

## 3. 下一阶段目标

当前不再以补基础设施为主，而是转向让这些能力稳定协同工作并形成自治闭环。

下一阶段目标：

1. **ADR-0015 代码落地**（Bundle-as-Repo Phase 1）
2. **Capability 模型代码落地**（ADR-0016 实现）
3. **Observation 统一接口代码落地**（ADR-0017 实现）
4. **MVP 闭环验证**：运行 → 发现优化 → 优化 → 再次运行 → before/after 对比

## 4. MVP 定义

最低可行的演化闭环：

1. ✅ Observation 事件 → 累积触发 → Optimizer 任务 → ReviewProposal → Implementer 任务（已验证）
2. ❌ Implementer 真的修改了 bundle repo 中的代码（需要 ADR-0015 落地）
3. ❌ 下一次 job 使用了修改后的 bundle（需要 bundle resolver 重新 resolve）
4. ❌ 有一个 before/after 的 observation 对比（需要 observation 查询支持时间窗口 + analyzer_version 定格）

新增闭环验证点（第二轮补齐）：

5. ❌ Finalize 失败时 finalize.failed 事件正确 emit（需要 capability finalize 错误处理实现）
6. ❌ Observation.consumed 事件正确去重（需要累积触发消费语义实现）

## 5. 约束

- 不回退到兼容层
- 不引入第二套协议或第二套 runtime 路径
- 计划优先体现为代码、测试、smoke，不体现为解释性文档堆积

## 6. 验收方式

每个阶段完成时都必须满足：

- 主路径代码闭环
- 受影响测试通过
- 至少一条端到端 smoke 通过
- 行为可以直接由代码和测试表达，而不是靠额外说明维持
