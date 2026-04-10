# Yoitsu System Plan

日期：2026-04-10
状态：文档层架构重构完成，进入代码落地阶段
范围：`yoitsu` / `yoitsu-contracts` / `trenni` / `palimpsest` / `pasloe`

## 1. 当前基线

已完成能力：

- canonical contract、runtime hardening、observation loop、external trigger、artifact runtime 均已落地
- 非 Git 任务已具备 artifact 输入/输出主链路
- GitHub 上下文、reviewer、PR 工具、外部触发入口已具备基本能力
- Phase 1 Autonomous Review Loop 端到端闭环验证通过

文档层架构重构（2026-04-10 完成）：

- `architecture.md` 全面重写，吸收 glossary 内容，确立统一概念体系
- 新增 [ADR-0016](docs/adr/0016-capability-model.md)：Capability 模型（setup + finalize 生命周期、Role 声明需求、Runtime 代发事件）
- 新增 [ADR-0017](docs/adr/0017-observation-unified-interface.md)：Observation 统一分析接口（Trenni 后置分析、统一注册表、按 bundle 分组）
- 更新 ADR-0010/0012/0015：语义合并，对齐 capability 和 observation 新模型
- `glossary.md` 合并回 `architecture.md` §9

## 2. 架构核心共识

1. **Event Store 为唯一因果权威**，不对内容可用性负责
2. **Artifact 为 first-class 概念**：身份(URI) + 因果(Event) + 可用性(Content Authority)
3. **Runtime 四阶段流水线**：preparation → context → agent loop → finalization
4. **Capability 模型**：setup + finalize，返回事件数据，runtime 代发，capability 间无排序
5. **Context fn 独立于 capability**：只读数据组装，服务 LLM prompt
6. **Task/Job 调度分离**：spawn 事件即边界，task 层将 task 物化为 job DAG
7. **Observation 统一接口**：Trenni 后置分析，默认和 bundle 提供的 analyzer 无区分，按 bundle/task 分组
8. **通过代码沉淀演化**：observation analyzer、capability、context provider、prompt 都是 bundle 中可演化的代码

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
4. ❌ 有一个 before/after 的 observation 对比（需要 observation 查询支持时间窗口）

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
