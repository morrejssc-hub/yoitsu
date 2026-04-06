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

## Batch 5: Observation Loop Closure ✅

### Step 1: 定 observation 读模型 ✅
- [x] 创建 Pasloe observation domain
- [x] 定义 BudgetVarianceDetail 读模型
- [x] 实现时间窗口查询接口
- [x] 实现聚合查询接口 (aggregate, by_role)
- [x] 创建数据库迁移

### Step 2: 补发射面 ✅
- [x] 盘点现有 observation.* 信号
  - budget_variance: trenni/supervisor._emit_budget_variance
  - preparation_failure: 新增 palimpsest/stages/preparation.py
  - tool_retry: 待实现（当前无 tool 重试机制）
- [x] budget_variance 发射路径测试
- [x] preparation_failure 发射点实现
- [x] preparation_failure 发射路径测试

### Step 3: 激活闭环 ✅
- [x] 修复 model_name_from_event_type 支持 observation.* 事件
- [x] 验证 domain registry 包含 observation
- [x] 验证 detail 创建和 payload 序列化
- [x] 验证聚合逻辑正确性
- [x] 端到端测试通过 (5 tests)

## Batch 6: GitHub Client and External Trigger Ingestion ✅

### Step 1: 统一 GitHub Client ✅
- [x] 盘点当前 GitHub API 调用位置
  - create_pr tool: tools.py (已迁移)
  - context loaders: 无 GitHub 调用
  - reviewer role: 无 GitHub 调用
- [x] 创建 palimpsest/runtime/github_client.py
- [x] 实现 PR 创建/查询接口
- [x] 实现 Issue 评论接口
- [x] 更新 create_pr tool 使用 GitHubClient
- [x] 添加 GitHubClient 测试

### Step 2: 外部 Trigger 接入 ✅
- [x] 定义外部事件格式
  - CIFailureEvent
  - IssueLabeledEvent
  - PRLabeledEvent
- [x] 添加 external trigger handler
  - supervisor._handle_external_event
  - supervisor._process_trigger
- [x] 事件转换逻辑
  - ci_failure_to_trigger
  - issue_labeled_to_trigger
  - pr_labeled_to_trigger
- [x] Label-to-role mapping

### Step 3: Reviewer GitHub 上下文 ✅
- [x] 定义 GitHub 上下文结构
  - GitHubPRContext
  - GitHubIssueContext
- [x] 创建 GitHub context loader
  - evo/contexts/loaders.py: github_context provider
- [x] 更新 reviewer role
  - 添加 github_context section
- [x] 更新 external events 注入 github_context
  - pr_labeled_to_trigger
  - issue_labeled_to_trigger

### Step 4: 端到端 Smoke Test ✅
- [x] PR labeled event -> TriggerData 转换
- [x] Issue labeled event -> TriggerData 转换
- [x] CI failure event -> TriggerData 转换
- [x] GitHub context 注入到 params
- [x] Context provider 渲染 GitHub 上下文
- [x] 完整流程测试: external event -> trigger -> context rendering

## Batch 7: Artifact Runtime Adoption (Phase 4) ✅

### Step 1: 盘点现有 Artifact 基础设施 ✅
- [x] ArtifactRef / ArtifactBinding 定义
- [x] ArtifactBackend 接口
- [x] LocalFSBackend 实现
- [x] 当前 publication 流程

### Step 2: Preparation Copy-In ✅
- [x] WorkspaceConfig.input_artifacts 字段
- [x] SpawnedJob.input_artifacts 字段
- [x] run_preparation() 中的 _materialize_input_artifacts()
- [x] from_enqueued_data/to_enqueued_data/to_launched_data 包含 input_artifacts

### Step 3: Publication ArtifactBinding ✅
- [x] publish_results() 返回 (git_ref, artifact_bindings) 元组
- [x] create_artifact_bindings() 存储 workspace tree
- [x] JobCompletedData.artifact_bindings 字段
- [x] runner.py 传递 artifact_bindings 到 JobCompletedData

### Step 4: 非 Git 任务 Smoke Path ✅
- [x] 纯 artifact 输入/输出验证
- [x] 非 Git 原生任务 smoke test (7 tests)
  - test_non_git_artifact_roundtrip: 完整 roundtrip
  - test_artifact_binding_in_job_completed_event: event 携带 bindings
  - test_blob_artifact_roundtrip: blob 单独验证
  - test_artifact_store_env_variable: env 配置验证
  - test_git_publication_returns_artifacts_for_repoless_workspace: P1 fix
  - test_default_store_root_consistency: P1 fix
  - test_artifact_materialization_after_clone: P1 fix

### P1 Fixes Applied ✅

#### Issue 1: git_publication() returns artifact_bindings for repoless workspace
- `palimpsest/runtime/roles.py:117` - Added `create_artifact_bindings()` call when `git.Repo()` fails
- Before: `(None, [])` returned, bypassing artifact output
- After: `(None, artifact_bindings)` returned for repoless workspace

#### Issue 2: input_artifacts propagated from SpawnedJob to runtime spec
- `trenni/runtime_builder.py:72` - Added `input_artifacts` parameter and merge into `workspace`
- `trenni/supervisor.py:295` - Added `input_artifacts` to `_launch_from_spawned()`
- `trenni/supervisor.py:985` - Added `input_artifacts` to `_launch()`
- Before: `job.input_artifacts` dropped entirely
- After: Propagated through full chain to `JobConfig.workspace.input_artifacts`

#### Issue 3: Default store root consistency
- `palimpsest/stages/publication.py:96` - Changed default to env or `~/.cache/palimpsest/artifacts`
- `palimpsest/stages/preparation.py:68` - Materialization happens AFTER clone
- Before: Publication wrote to `<workspace>/.artifacts`, preparation read from env default
- After: Both use same default store root
- Before: Artifacts materialized before clone (conflict)
- After: Clone first, then overlay artifacts

### Second Round P1 Fixes ✅

#### Issue 1: input_artifacts enters canonical trigger/spawn protocol
- `yoitsu-contracts/events.py:TriggerData` - Added `input_artifacts` field
- `yoitsu-contracts/events.py:SpawnTaskData` - Added `input_artifacts` field
- `yoitsu-contracts/events.py:SupervisorJobEnqueuedData` - Added `input_artifacts` field
- `yoitsu-contracts/events.py:SupervisorJobLaunchedData` - Added `input_artifacts` field
- `trenni/spawn_handler.py` - Pass `input_artifacts` from `SpawnTaskData` to `SpawnedJob`
- `yoitsu/cli.py` - Accept `input_artifacts` in submit command
- Before: External triggers/spawns cannot declare input artifacts
- After: Full protocol chain from trigger to runtime spec

#### Issue 2: input_artifacts preserved through enqueue replay
- `SupervisorJobEnqueuedData.input_artifacts` field added
- `model_validate().model_dump()` now preserves `input_artifacts`
- Before: Field dropped during schema validation, lost on restart
- After: Field preserved through full replay cycle

#### Issue 3: Complete trigger/spawn -> runtime spec chain
- All canonical protocol models now include `input_artifacts`
- RuntimeSpecBuilder propagates from `SpawnedJob.input_artifacts`
- Before: Chain broken at multiple points
- After: End-to-end propagation verified by tests

### Third Round P1 Fixes ✅

#### Issue 1: spawn tool accepts input_artifacts
- `palimpsest/runtime/tools.py:_SPAWN_SCHEMA` - Added `input_artifacts` to schema
- `palimpsest/runtime/tools.py:_normalize_spawn_task()` - Parse and pass `input_artifacts`
- Before: LLM spawn tool cannot declare artifact inputs
- After: Child tasks can receive artifacts from parent
- Test: `test_spawn_tool_accepts_input_artifacts`

#### Issue 2: trigger path propagates input_artifacts to SpawnedJob
- `trenni/supervisor.py:448` - Added `input_artifacts` when constructing root `SpawnedJob`
- Before: `TriggerData.input_artifacts` ignored by `_process_trigger()`
- After: Root job receives artifacts from external trigger
- Test: `test_trigger_data_input_artifacts_to_spawned_job`

#### Issue 3: launched-event replay preserves input_artifacts
- `trenni/supervisor.py:1482` - Read `input_artifacts` from event data in `_register_replayed_launch()`
- Before: Field lost when replaying launched jobs after restart
- After: Restored correctly from event store
- Test: `test_launched_event_replay_preserves_input_artifacts`

## 验收状态

- [x] 搜索主代码目录，不再出现 legacy key 的协议级用法 ✅
- [x] 搜索主代码目录，不再出现针对旧输入形态的 fallback 逻辑 ✅
- [x] prompt、examples、CLI、contracts、runtime 使用同一套字段命名 ✅
- [x] supervisor.job.launched 等关键事件不再包含空壳语义 ✅
- [x] 主链路模块数量更少，数据搬运层级更浅 ✅
- [x] 文档只解释原则和边界，不再解释代码已经能直接表达的细节 ✅
- [x] 字段搬运逻辑收敛到 SpawnedJob 转换方法中 ✅
- [x] Budget 不再因入口、继承、重放路径发生漂移 ✅
- [x] Preparation 能从 ArtifactStore 读取 artifacts ✅ (Phase 4 Step 2)
- [x] Publication 能产出 ArtifactBinding ✅ (Phase 4 Step 3)
- [x] 非 Git 任务 smoke path 通过 ✅ (Phase 4 Step 4)

## 测试结果

- **Yoitsu-contracts tests**: 91 passed ✅ (85 + 6 new protocol tests)
- **Trenni tests**: 205 passed ✅ (200 + 5 propagation tests)
- **Palimpsest tests**: 185 passed ✅ (177 + 8 artifact smoke tests)
- **Root tests**: 47 passed ✅