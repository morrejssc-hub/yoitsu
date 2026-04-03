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

## Batch 3: Scaffold Deletion + Structural Collapse

### Phase 5: Delete Dead Scaffolds ✅
- [x] 删除未接入主流程的 scaffold (trigger_evaluator.py)
- [x] 删除旧架构绑定脚本
- [x] 删除已归档 ADR 残留注释 (通过 git mv 到 archive)
- [x] 合并重复脚本 (scripts 都是运维脚本，保留)

### Phase 6: Structural Collapse (Deferred)
- [ ] 精简 Trenni supervisor 边界 (需要更多分析)
- [ ] 明确 intake path 与 execution path 接口
- [ ] 合并重复数据搬运对象
- [ ] 收敛转换边界

## 验收状态

- [x] 搜索主代码目录，不再出现 legacy key 的协议级用法 ✅
- [x] 搜索主代码目录，不再出现针对旧输入形态的 fallback 逻辑 ✅
- [x] prompt、examples、CLI、contracts、runtime 使用同一套字段命名 ✅
- [x] supervisor.job.launched 等关键事件不再包含空壳语义 ✅
- [ ] 主链路模块数量更少，数据搬运层级更浅 (Phase 6)
- [x] 文档只解释原则和边界，不再解释代码已经能直接表达的细节 ✅

## 测试结果

- **Trenni tests**: 192 passed, 1 failed (外部依赖 uuid_utils 缺失)
- **Palimpsest tests**: 需要单独验证
- **yoitsu-contracts tests**: 需要单独验证