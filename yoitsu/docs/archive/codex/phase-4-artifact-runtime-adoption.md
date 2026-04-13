# Phase 4: Artifact Runtime Adoption

日期：2026-04-03
状态：已完成 ✅
范围：`palimpsest` / `yoitsu-contracts` / `trenni`

## 目标

让 Artifact Store 从 "contracts 与 backend 已存在" 走到 "runtime 主链路真的消费它"。

## 执行顺序

### Step 1: 盘点现有 Artifact 基础设施 ✅

盘点：
- ArtifactRef / ArtifactBinding 定义
- ArtifactBackend 接口
- LocalFSBackend 实现
- 当前 publication 流程

### Step 2: Preparation Copy-In ✅

在 preparation 阶段接入 artifact materialization：
- 从 ArtifactStore 读取输入 artifacts
- 将 artifacts 写入 workspace

已实现：
- `WorkspaceConfig.input_artifacts` 字段
- `SpawnedJob.input_artifacts` 字段
- `run_preparation()` 中的 `_materialize_input_artifacts()` 函数

### Step 3: Publication ArtifactBinding ✅

在 publication 阶段产出真实 ArtifactBinding：
- 收集输出文件
- 创建 ArtifactRef
- 生成 ArtifactBinding

已实现：
- `publish_results()` 返回 `(git_ref, artifact_bindings)` 元组
- `create_artifact_bindings()` 函数存储 workspace tree
- `JobCompletedData.artifact_bindings` 字段

### Step 4: 非 Git 任务 Smoke Path ✅

验证非 Git 原生任务：
- 纯 artifact 输入
- 纯 artifact 输出
- 不依赖 git_ref

已实现 7 个 smoke tests:
- test_non_git_artifact_roundtrip: 完整 roundtrip
- test_artifact_binding_in_job_completed_event: event 携带 bindings
- test_blob_artifact_roundtrip: blob 单独验证
- test_artifact_store_env_variable: env 配置验证
- test_git_publication_returns_artifacts_for_repoless_workspace: P1 fix
- test_default_store_root_consistency: P1 fix
- test_artifact_materialization_after_clone: P1 fix

## 完成标志

- git_ref 退化为兼容收据，而不是唯一交付通道
- 非 Git 原生任务可以在不依赖 Git 的情况下完成输入物化与结果固化

## 最小验收标准

- [x] Preparation 能从 ArtifactStore 读取 artifacts
- [x] Publication 能产出 ArtifactBinding
- [x] 有非 Git 任务的 smoke path 通过 (7 tests)

### P1 Fixes Applied

#### Issue 1: git_publication() returns artifact_bindings for repoless workspace
- **Fix**: `palimpsest/runtime/roles.py` - Added `create_artifact_bindings()` call when `git.Repo()` fails
- **Test**: `test_git_publication_returns_artifacts_for_repoless_workspace` verifies artifact bindings returned

#### Issue 2: input_artifacts propagated from SpawnedJob to runtime spec
- **Fix**: `trenni/runtime_builder.py` - Added `input_artifacts` parameter and merge into `workspace`
- **Fix**: `trenni/supervisor.py` - Added `input_artifacts` to `_launch()` and `_launch_from_spawned()`
- **Test**: `test_input_artifacts_propagated_to_runtime_spec` verifies propagation

#### Issue 3: Default store root consistency
- **Fix**: `palimpsest/stages/publication.py` - Changed default to `PALIMPSEST_ARTIFACT_STORE` env or `~/.cache/palimpsest/artifacts`
- **Fix**: `palimpsest/stages/preparation.py` - Materialization happens AFTER clone to avoid conflict
- **Test**: `test_default_store_root_consistency` verifies roundtrip
- **Test**: `test_artifact_materialization_after_clone` verifies clone+artifacts order
