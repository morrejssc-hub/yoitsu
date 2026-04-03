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

### Phase 5: Delete Dead Scaffolds
- [ ] 删除未接入主流程的 scaffold
- [ ] 删除旧架构绑定脚本
- [ ] 删除已归档 ADR 残留注释
- [ ] 合并重复脚本

### Phase 6: Structural Collapse
- [ ] 精简 Trenni supervisor 边界
- [ ] 明确 intake path 与 execution path 接口
- [ ] 合并重复数据搬运对象
- [ ] 收敛转换边界