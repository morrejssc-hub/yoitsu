# Code Simplification Progress

## Batch 1: Contract + Runtime Cutover ✅

### Phase 1: Contract Reset ✅
- [x] 重写 yoitsu-contracts 中 task/spawn/launch 相关模型
- [x] 删除 SpawnTaskData.prompt
- [x] 将 repo 与 init_branch 作为明确字段
- [x] 增加严格校验，拒绝 legacy key
- [x] 清理旧字段相关测试

### Phase 2: Runtime Path Cutover ✅
- [x] 重写 palimpsest spawn task normalization
- [x] 重写 trenni spawn expansion
- [x] 删除 legacy fallback 分支
- [x] 统一 root trigger 与 child spawn 的 repo context shape

## Batch 2: CLI/Prompt/Example + Event Pruning ✅

### Phase 3: CLI/Prompt/Example Unification ✅
- [x] yoitsu submit 只接受 canonical YAML
- [x] 删除旧输入别名
- [x] 重写 planner prompts
- [x] 重写 examples 和 smoke tasks
- [x] 调整 CLI 事件展示

### Phase 4: Event Surface Pruning ✅
- [x] 审视 SupervisorJobLaunchedData
- [x] 删除 llm/workspace/publication 空壳字段
- [x] 同步精简事件消费者

## Batch 3: Scaffold Deletion + Structural Collapse ✅

### Phase 5: Delete Dead Scaffolds ✅
- [x] 删除未接入主流程的 scaffold (trigger_evaluator.py)
- [x] 删除旧架构绑定脚本
- [x] 删除已归档 ADR 残留注释 (通过 git mv 到 archive)
- [x] 合并重复脚本 (scripts 都是运维脚本，保留)

### Phase 6: Structural Collapse ✅
- [x] 添加 SpawnedJob.to_enqueued_data() 方法
- [x] 添加 SpawnedJob.to_launched_data() 方法
- [x] 添加 SpawnedJob.from_enqueued_data() 方法
- [x] 更新 supervisor.py 使用转换方法
- [x] 简化事件创建逻辑 (不再手动逐字段拷贝)
- [x] 简化 replay 逻辑 (不再手动逐字段重建)
- [x] Budget replay fidelity 已修复

## Batch 4: Runtime Hardening ✅

### Task 1: Intake / Execution 分相隔离
- [x] 分析当前 intake/execution 边界
- [x] 明确 intake path 只做事件验证和 spawn planning
- [x] 明确 execution path 只做 runtime 操作
- [x] 分离错误处理逻辑

### Task 2: Tool 子进程隔离与硬超时
- [x] 评估当前 builtin tools 风险等级
- [x] 为高风险工具增加超时机制

### Task 3: Budget 不变量补齐 ✅
- [x] Budget >= 0 验证 (ge=0.0 constraint)
- [x] Join job budget 继承规则已正确实现
- [x] Replay budget 一致性已修复

### Task 4: 补齐回归测试 ✅
- [x] Intake 失败场景测试 (budget 验证失败)
- [x] Execution 失败场景测试 (launch 失败 cleanup)
- [x] Replay 路径测试 (使用 canonical 字段)
- [x] Cleanup 路径测试 (container 清理)

## Batch 5: Observation Loop Closure (In Progress)

### Step 1: 定 observation 读模型
- [x] 创建 Pasloe observation domain
- [x] 定义 BudgetVarianceDetail 读模型
- [x] 实现时间窗口查询接口
- [x] 实现聚合查询接口 (aggregate, by_role)
- [ ] 创建数据库迁移

### Step 2: 补发射面
- [ ] 盘点现有 observation.* 信号
- [ ] 补齐缺口

### Step 3: 激活闭环
- [ ] 实现累积阈值触发逻辑
- [ ] Review Task 读取聚合结果
- [ ] 端到端 smoke test

## 验收状态

- [x] 搜索主代码目录，不再出现 legacy key 的协议级用法 ✅
- [x] 搜索主代码目录，不再出现针对旧输入形态的 fallback 逻辑 ✅
- [x] prompt、examples、CLI、contracts、runtime 使用同一套字段命名 ✅
- [x] supervisor.job.launched 等关键事件不再包含空壳语义 ✅
- [x] 主链路模块数量更少，数据搬运层级更浅 ✅
- [x] 文档只解释原则和边界，不再解释代码已经能直接表达的细节 ✅
- [x] 字段搬运逻辑收敛到 SpawnedJob 转换方法中 ✅
- [x] Budget 不再因入口、继承、重放路径发生漂移 ✅

## 测试结果

- **Trenni tests**: 193 passed ✅
- **Palimpsest tests**: 156 passed ✅
- **Yoitsu tests**: 47 passed ✅