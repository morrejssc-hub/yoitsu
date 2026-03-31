# Yoitsu TODO

## 近期清理项

- [ ] `SpawnTaskData` 中的 `prompt` 和 `params` 字段（deprecated，backward compat 用，可在下次清理 commit 中删除）
- [ ] `SupervisorJobLaunchedData` / `SupervisorJobEnqueuedData` 的 `llm`/`workspace`/`publication` 字段语义更新为 resolved config（ADR-0007 D8，当前仍是 override delta）
- [ ] SpawnHandler 回归测试：expand 后断言 `role_params` 不含 `goal`/`budget`
- [ ] SpawnHandler 回归测试：join job `parent_summary` 位置 + `role_params == {mode: join}`

---

## 路线图

依赖关系：
```
GitHub client
    ├── 外部任务流入 (CI failures / issues → trigger)   ← 解决冷启动
    └── Reviewer role (review → merge)                  ← 关闭交付闭环
            ↓
        任务量积累
            ↓
        内部监控 (event stream 分析)
            ↓
        自优化 (主动 dispatch 优化任务)
```

### 第一步：GitHub client

统一 GitHub API 层，供 tool 和 context provider 共用。当前 `create_pr` 只是单点调用，需要扩展：
- PR 状态和 CI check 结果查询
- Review comments 读写
- Merge 操作（条件化，供 reviewer role 使用）
- Issue 读取（供外部任务触发使用）

### 第二步：外部任务流入（解冷启动）

持续的真实任务流是演化的前提，没有它监控和自优化都没有信号。

- **CI failure → trigger**：GitHub webhook 监听 CI 失败事件，构造 Pasloe trigger（修复失败的 CI）
- **Issue → trigger**：GitHub issue 打特定 label 触发任务（例如 `yoitsu-task`）
- Pasloe trigger API 已就绪，主要工作在 webhook 接收和 trigger 构造侧

### 第三步：Reviewer role

关闭 spawn/eval/join/publish/review/merge 的完整闭环。

- **第一阶段**：review-only，产出结构化评审意见，不 auto-merge
- **第二阶段**：eval 稳定后，merge 条件化在 `eval verdict=pass` 上，而非无条件
- 需要 GitHub client（PR diff、CI status、existing comments 作为 context）

### 第四步：Pasloe 查询能力

为未来自监控准备数据接口，不急着写分析逻辑。

- event stream 的任务维度查询（按 task_id subtree、按 team version、按时间段）
- eval verdict 聚合查询（成功率、常见失败模式）
- 目标：让自监控任务能方便地从 Pasloe 拿到所需数据

### 第五步：自优化 loop

演化的核心机制，必须在前四步稳定运行且有足够任务量后才启动。过早启动会因为信号不足而退化（历史教训）。

- event stream 分析 → 识别优化机会（context 缺口、prompt 效率、spawn 模式）
- 优化机会 → dispatch 普通任务（修改 evo/，跑测试，eval）
- 无需单独的"演化进程"，就是普通任务流

---

## 已完成

### ADR-0004/0008/0009/0010：预算预测、任务创建、准备函数、自优化（2026-03-31）

实现了预算作为预测而非强制约束、spawn 默认 planner 角色、PreparationConfig 命名、observation 事件类型和 budget_variance 发射。185 个测试全部通过。

**主要更改：**
- RoleMetadata 添加 max_cost 字段，spawn 时验证
- 移除 cost-based termination，保留 tracking 用于 observation
- spawn 无 role 时默认 planner
- PreparationConfig 作为 WorkspaceConfig 别名
- observation.budget_variance 事件发射
- trigger evaluator scaffold

### ADR-0007：Task/Job 信息边界（2026-03-29）

清理了 task/job 层级的混淆：goal 单通道、budget 单通道、spawn payload 不携带执行配置、RoleMetadataReader 提取到 yoitsu-contracts、role catalog 按 evo SHA 失效。163 个测试全部通过。
