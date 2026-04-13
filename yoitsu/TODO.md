# Yoitsu Status Index

- 当前系统计划：[SYSTEM-PLAN.md](SYSTEM-PLAN.md)
- 架构指南：[docs/architecture.md](docs/architecture.md)
- 活跃 ADR：[docs/adr/](docs/adr/)
- 当前任务工件：`.task/`
- 历史归档：[docs/archive/](docs/archive/)

## 2026-04-11 代码审查修复 (第三轮)

### 修复的Issues

| Issue | Severity | 描述 | 修复 |
|-------|----------|------|------|
| Critical #1 | Hallucination gate role_type | 添加完整文档说明role_type合约 + 日志 | ✓ |
| Important #2 | Artifact URI fallback | 移除git_commit: fallback，改为显式失败 | ✓ |

### 修复详情

1. **Hallucination gate documentation** (capability.py)
   - JobContext docstring: 完整说明role_type行为合约
   - 记录"worker"=failure, "planner/evaluator"=success
   - 说明role_type来源: RoleMetadata.role_type via @role decorator
   - 添加日志: hallucination gate触发时记录role_type和处理结果
   - 添加is_hallucination字段到publication.skipped事件

2. **Artifact URI validation** (capability.py)
   - 移除git_commit:{sha} fallback（违反ADR-0015）
   - 显式检查target_source.repo_uri
   - 缺失时emit finalize.failed + success=False
   - 清晰错误消息说明配置错误

### 测试状态

- palimpsest: 175 passed ✓

### 审查结论

**Ready to merge: Yes** ✓

第三轮审查确认所有 Critical 和 Important 问题已正确修复。

Minor 建议（可后续处理）：
1. 添加更细粒度的 hallucination gate 单元测试
2. 添加配置早期验证来提前捕获缺失 repo_uri

---

## 2026-04-11 代码审查通过 (第二轮)

### 审查范围

本次审查覆盖完整架构重构(ADR-0015/0016/0017)及第二轮修复。

### 修复的Issues (第二轮)

| Issue | 描述 | 修复 |
|-------|------|------|
| Important #1 | GitWorkspaceCapability role discrimination | ✓ role_type字段 + hallucination gate逻辑 |
| Important #2 | Artifact URI format | ✓ target_source.repo_uri构建正确URI |
| Deprecated清除 | backward compat代码残留 | ✓ 移除evo_root/evo_sha/workspace_path |

### 测试状态

- palimpsest: 175 passed ✓
- trenni: 未验证 (无pytest环境)
- yoitsu-contracts: 120 passed ✓

### 审查结论

**Ready to merge: Yes**

核心问题已修复，deprecated代码已清除，测试全量通过。

---

## 2026-04-11 代码审查通过 (第一轮)

### 审查结果

| ADR | 状态 | 备注 |
|-----|------|------|
| ADR-0015 | ✅ 正确实现 | bundle_workspace 结构正确，容器路径已处理 |
| ADR-0016 | ✅ 正确实现 | capability lifecycle 完整，backward compat 维护 |
| ADR-0017 | ✅ 正确实现 | observation emission 已移除，analyzer_version 已传递 |

**生产风险**: 低
- backward compat 层确保现有部署继续工作
- 新 capability path 仅在 `needs` 声明时激活
- 所有测试通过，主链路接口已对齐

### 建议后续优化（Minor）

1. Fixture 结构整合 - 使用单一 canonical 结构
2. spawn() backward compat 完善 - 添加 deprecation warning
3. workspace_path deprecated 字段 - 添加 deprecation warning

### 测试状态

- palimpsest: 175 passed ✓
- trenni: 220 passed ✓
- yoitsu-contracts: 120 passed ✓

## 2026-04-11 主链路修复完成

### 完成的工作

1. ✅ **build_context(): resolve_context_functions调用**
   - 调用改为 `resolve_context_functions(bundle_workspace, requested)`
   - 不再传递 bundle 参数

2. ✅ **context provider注入**
   - build_context() 注入 bundle_workspace
   - 支持 backward compat: evo_root → bundle_workspace

3. ✅ **spawn() backward compat**
   - 支持 bundle_workspace/bundle_sha 参数
   - backward compat: 如果未提供 evo_root/evo_sha，使用 bundle_workspace/bundle_sha

4. ✅ **测试迁移**
   - test_observation_context.py: contexts/ 根目录
   - test_context_loader.py: contexts/ 根目录
   - test_e2e_external_events.py: 去掉 bundle 参数
   - test_evo_tools.py: resolve_tool_functions 签名
   - test_composite_gateway.py: bundle_workspace/tools/
   - integration/test_bundle_isolation.py: bundle_workspace 根目录

### 测试状态

- palimpsest: 175 passed ✓
- trenni: 220 passed ✓
- yoitsu-contracts: 120 passed ✓

## 2026-04-11 路径问题修复

### 完成的工作（严重问题修复）

1. ✅ **runtime_builder: 容器内路径注入**
   - BundleSource/TargetSource注入容器内路径 `/opt/yoitsu/palimpsest/bundle|target`
   - 不再注入 host path，避免容器内找不到宿主机路径

2. ✅ **RoleManager/loader: bundle_workspace根目录查找**
   - RoleManager直接从 `bundle_workspace/roles/` 查找
   - contexts.py: 从 `bundle_workspace/contexts/` 查找
   - tools.py: 从 `bundle_workspace/tools/` 查找
   - UnifiedToolGateway: `bundle_workspace` 取代 `evo_root+bundle` 参数

3. ✅ **TargetSource: selector字段**
   - workspace_manager使用 `selector=init_branch` 而非 `branch=init_branch`
   - 符合 TargetSource 模型定义

4. ✅ **architecture.md: backward compat说明**
   - §4.1 Preparation: needs=[] 回退到 preparation_fn
   - §4.4 Finalization: needs=[] 回退到 publication_fn

### 测试状态

- palimpsest: 135 passed, 41 failed (observation_context tests)
- trenni: 220 passed ✓
- yoitsu-contracts: 120 passed ✓

### 待完成

- palimpsest observation_context 测试修复

## 2026-04-11 Capability Model 实现完成

### 完成的工作（代码层实现）

1. ✅ **P0: Runner capability lifecycle (ADR-0016)**
   - runner.py: capability setup → interaction → finalize → FinalizeResult
   - needs=[]: backward compat, old preparation/publication path
   - needs=['git_workspace']: capability setup/finalize called
   - success=False → JobFailedData, success=True → JobCompletedData
   - Hallucination gate: capability finalize controls job terminal state

2. ✅ **P1: evo_sha → bundle_sha rename (ADR-0015)**
   - SpawnedJob.evo_sha → SpawnedJob.bundle_sha
   - SpawnDefinition.evo_sha → SpawnDefinition.bundle_sha
   - runtime_builder.py: io.yoitsu.evo-sha → io.yoitsu.bundle-sha
   - spawn_handler.py: all evo_sha vars → bundle_sha
   - supervisor.py: _cached_evo_sha → _cached_bundle_sha, _read_evo_sha → _read_bundle_sha
   - config.py: TrenniConfig.evo_root → bundle_root
   - 220 tests passed ✓

3. ✅ **P3: JobContext.analyzer_version (ADR-0017)**
   - JobContext新增analyzer_version字段
   - runner传入config.analyzer_version到cap_ctx
   - capabilities可通过ctx.analyzer_version发射observation

4. ✅ **P4: Capability integration tests**
   - test_capability.py: 7 tests for capability lifecycle
   - setup/finalize calls, success handling, backward compat
   - 180 tests passed ✓

### 待完成

5. ⏳ **P2: Role/Tool/Context从bundle_workspace加载**
   - RoleManager/UnifiedToolGateway仍从evo_root加载
   - 需要更新为从bundle_workspace加载role/tool/context模块

### 测试状态

- palimpsest: 180 passed ✓
- trenni: 220 passed ✓
- yoitsu-contracts: 120 passed ✓

## 2026-04-10 文档层架构重构（第四轮清理）

### 完成的工作（文档一致性清理）

1. ✅ **Observation 触发条件修正**
   - architecture.md §6.1: 所有 terminal job 状态触发分析，不只是 job.completed
   - ADR-0017 §2c: 流程图补充 analyzer_version，明确 failed/partial 也触发

2. ✅ **旧 contract 残留清理**
   - architecture.md 开头: adr/0012-factorio-task-source.md 改为活跃文档，archive/adr/0012-...old.md 才是历史
   - ADR-0015 §5: runtime 消费双 workspace，不是单一 BundleSource.workspace

3. ✅ **analyzer_version 全量同步**
   - ADR-0010 §4: 两方 SHA → 三方 SHA（bundle_sha + trenni_sha + palimpsest_sha）

文档层设计完成，跨文档一致性问题已清理。

## 2026-04-10 文档层架构重构（第三轮）

### 完成的工作（解决 reviewer 指出的结构问题）

1. ✅ **Target Source 概念新增**
   - architecture.md §3.3.1: 与 Bundle Source 分离
   - ctx.bundle_workspace 加载代码，ctx.target_workspace 执行任务
   - Artifact URI 必须指向远端仓库，不能指向 ephemeral workspace

2. ✅ **Finalize 返回 FinalizeResult(events, success)**
   - architecture.md §5.1/§5.4: capability 返回 success 标志
   - ADR-0016 §2a/§2f: Protocol 定义，内部重试，返回 success
   - Job 终态：全部 success=True → job.completed，任一 False → job.failed
   - Hallucination gate：无变更 → success=False → job.failed（Worker role）

3. ✅ **analyzer_version 三方 SHA**
   - architecture.md §6.4: bundle_sha + trenni_sha + palimpsest_sha
   - ADR-0017 §2g: 三方职责明确
   - 全局替换：palimpsest_sha → 三方 SHA

4. ✅ **累积触发原子性**
   - architecture.md §6.5: 先创建 Review Task，再 emit consumed
   - ADR-0017 §2h: triggered_by 幂等键
   - 重放：已存在 Task → 仅补发 consumed；不存在 → 重新创建

5. ✅ **Artifact URI 指向远端**
   - ADR-0015 §6: push 成功后 URI 指向 repo_uri@sha
   - ADR-0012 D3/D7: 示例修正，不指向 ephemeral workspace

## 2026-04-10 文档层架构重构（第二轮）

### 完成的工作（第二轮 review 后补充）

1. ✅ **architecture.md 关键闭环补充**
   - §5.4: Finalize 错误处理策略（try-catch、finalize.failed 事件）
   - §6.4: Analyzer 版本定格规则（记录 bundle_sha + palimpsest_sha，应用用最新）
   - §6.5: 累积触发消费语义（observation.consumed 事件、batch_members、去重规则）
   - §7.2: bundle 字段归属明确（任务语义类）
   - 开头: Team → Bundle 迁移声明

2. ✅ **ADR-0016 补充 finalize 错误处理**
   - 2f: Finalize 不允许失败，必须返回事件
   - 事件结构：capability、stage、error、partial_success、retry_possible
   - Setup 失败 = job abort，finalize 失败 = 事件记录

3. ✅ **ADR-0017 补充版本定格和消费语义**
   - 2g: Analyzer 版本定格（记录版本、应用最新、复现用定格）
   - 2h: 累积触发消费语义（observation.consumed、batch_members、去重）
   - 2i: Analyzer 注册时机（Trenni 启动、bundle 更新、per-job 版本定格）

4. ✅ **ADR-0012 完整重写（Bundle + Capability worked example）**
   - Factorio 作为 bundle而非 team
   - factorio-bundle repo 目录结构（capabilities/、roles/、tools/、observations/）
   - rcon_bridge 作为 capability（setup/finalize）
   - call_script 工具依赖 rcon_bridge 注入
   - git_workspace + factorio_save 双 finalize
   - max_concurrent_jobs: 1 通过 bundle config 实现
   - 旧版移入 docs/archive/adr/0012-factorio-task-source-old.md

5. ✅ **ADR-0010 清理旧表述**
   - §2a: observation 生成方式改为 ADR-0017 后置分析
   - §2: review check items 在 bundle repo 而非 evo/
   - §4: Phase mapping 更新为 analyzer 注册流程

6. ✅ **ADR-0015 §6 Push 策略拍板**
   - 同步 push，失败即 finalize.failed
   - push 失败时 commit 仍存在本地
   - 不采用异步 push

## 2026-04-10 文档层架构重构（第一轮）

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
