# Yoitsu Status Index

- 当前系统计划：[SYSTEM-PLAN.md](SYSTEM-PLAN.md)
- 架构指南：[docs/architecture.md](docs/architecture.md)
- 活跃 ADR：[docs/adr/](docs/adr/)
- 当前任务工件：`.task/`
- 历史归档：[docs/archive/](docs/archive/)

## 2026-04-10 文档层架构重构

### 完成的工作

1. ✅ **architecture.md 全面重写**
   - 吸收 glossary.md 内容
   - 确立 Event Store 为唯一因果权威
   - 定义 Artifact 三属性模型（身份 + 因果 + 可用性）
   - 定义 Runtime 四阶段流水线（preparation → context → agent loop → finalization）
   - 整合 Bundle 模型、URI 合同、编排边界

2. ✅ **新增 ADR-0016: Capability 模型**
   - Capability = setup + finalize 生命周期
   - Role 声明 `needs` 列表
   - Capability 返回事件数据，runtime 代发
   - Capability 之间无排序依赖
   - Finalize 合并 publication 和 cleanup

3. ✅ **新增 ADR-0017: Observation 统一分析接口**
   - Trenni 后置分析（非实时）
   - 默认与 bundle 提供的 analyzer 无区分
   - 按 bundle + task_id 分组
   - Analyzer 可随 bundle 演化

4. ✅ **现有 ADR 语义合并**
   - ADR-0010: 信号触发从实时改为后置分析，evo/ 改为 bundle repo
   - ADR-0012: Factorio 隔离方案用 capability 模型重写
   - ADR-0015: Bundle 目录结构新增 capabilities/ 和 observations/

5. ✅ **glossary.md 合并回 architecture.md**

## 2026-04-08 完成的工作

### Phase 1: Autonomous Review Loop ✅ 完成

完整事件链验证成功：
1. ✅ Observation 事件发出
2. ✅ 聚合查询成功 (X-API-Key header 修复)
3. ✅ 阈值判断正确
4. ✅ Optimizer 任务启动 (bundle="default" 修复)
5. ✅ Optimizer 输出完整 ReviewProposal (summary 4096 修复)
6. ✅ ReviewProposal 解析成功
7. ✅ Implementer 任务创建

**修复的 bug**：
1. `observation_aggregator.py`: 使用 X-API-Key header（而非 Authorization: Bearer）
2. `supervisor.py`: 为 optimizer 任务设置 bundle="default"
3. `interaction.py` + `publication.py`: summary 截断从 500 改为 4096
4. 创建 `evo/default/roles/optimizer.py`: 默认 optimizer 角色定义

**提交记录**：
- trenni: `faf3762` - fix(optimization-loop): fix two bugs
- palimpsest: `66bb004` - fix(interaction): increase summary truncation limit
- yoitsu: `c9a55be` - feat(optimizer): add default bundle optimizer role
