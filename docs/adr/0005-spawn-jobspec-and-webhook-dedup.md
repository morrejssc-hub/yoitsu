# ADR-0005: Spawn 使用 `prompt + job_spec`，Webhook 推进 Cursor 并按 Event ID 幂等

- **状态**: 已实施
- **日期**: 2026-03-24
- **决策者**: holo, Codex
- **关联**: ADR-0001、ADR-0004、`2026-03-23-podman-job-runtime-design.md`

## 背景

在 Quadlet + Podman-per-job 部署跑通之后，继续做 fork/fan-out smoke test 时暴露出三类结构性问题：

1. **`job.spawn.request` 的 child payload 语义不完整**
   - 父任务调用 `spawn()` 时，child 往往只带一个松散 dict
   - `palimpsest` 侧更倾向使用 `prompt`
   - `trenni` 侧只消费 `task`
   - repo / branch / role / evo SHA / 各类 override 的继承规则没有明确 contract

2. **Webhook + Poll fallback 组合下，`job.spawn.request` 会被重复处理**
   - webhook 到来时直接调用 `_handle_event()`
   - poll fallback 仍会从旧 cursor 再次拉到同一事件
   - 当前 cursor 只在 polling 路径推进，webhook 路径不推进
   - 结果是同一个 `job.spawn.request` 被处理两次，child job 重复 launch

3. **空变更路径下缺少 Git author identity**
   - spawn child 常常只是分析型任务，不一定产生文件修改
   - publication 会走 `git commit --allow-empty`
   - 容器内没有 `user.name` / `user.email` 时，任务会在空提交路径失败

这些问题不是局部小 bug，而是 runtime contract 不完整的表现。

## 决策

### 决策 1: `spawn` child contract 升级为 `prompt + job_spec`

**采纳**。

`job.spawn.request` 的 `tasks` 不再视为任意松散 dict 列表，而是显式结构：

```json
{
  "prompt": "...",
  "job_spec": {
    "repo": "...",
    "init_branch": "...",
    "role": "...",
    "evo_sha": "...",
    "llm": {...},
    "workspace": {...},
    "publication": {...}
  }
}
```

其中：

- `prompt` 定义 child 真正要做的工作
- `job_spec` 定义 child 在哪个仓库、哪个分支、以哪个角色、基于哪个 evo 版本执行

### 决策 1.1: 保留旧字段兼容，但只作为 fallback

为避免一次性打断现有 evo prompt，以下旧字段仍短期兼容：

- `task` -> 兼容映射到 `prompt`
- `role`
- `role_file`
- `role_sha`
- `repo`
- `branch`
- `init_branch`

但 runtime 内部统一归一化到 `prompt + job_spec`。

### 决策 1.2: 默认值继承优先减轻心智负担

child `job_spec` 缺字段时，从父任务继承默认值：

| 字段 | 默认来源 |
|------|----------|
| `repo` | 父任务已 launch 的 repo |
| `init_branch` | 父任务已 launch 的 branch |
| `role` | 父任务 role，缺省再落到 `default` |
| `evo_sha` | 父任务当前 evo SHA |
| `llm` | 父任务 override 与系统默认合并 |
| `workspace` | 父任务 override 与系统默认合并 |
| `publication` | 父任务 override 与系统默认合并 |

这意味着：

- 制定 plan 时仍然可以明确指定 job spec
- 实际调用 `spawn()` 时多数 child 只需要提供 `prompt`
- 只有偏离父任务上下文时才需要显式覆盖 repo / branch / role

### 决策 2: Webhook 接收事件时推进 Cursor，并重置 Poll fallback 计时

**采纳**。

当 `/hooks/events` 接收到 Pasloe 推送事件时：

1. 先用该事件 `(ts, id)` 推进 `event_cursor`
2. 再重置 webhook fallback poll 的下一次触发时间

这样 polling 不会立刻再把刚刚通过 webhook 处理过的事件拉回来。

### 决策 2.1: Supervisor 的幂等键提升为所有事件的 `event.id`

**采纳**。

不再只对 `task.submit` 维护去重集合，而是对所有经 `_handle_event()` 进入的事件统一按 `event.id` 去重。

理由：

- Pasloe 已经提供稳定事件 `id`
- queue 内去重不是充分条件，因为队列会被消费
- 真正需要幂等的是“事件被 supervisor 执行过没有”，不是“某个 job_id 是否还在队列里”

### 决策 3: Workspace 建立后必须保证 repo-local Git identity

**采纳**。

`setup_workspace()` 在 repo 建立或 clone 完成后，都会确保本地仓库级别存在：

- `user.name`
- `user.email`

优先级：

1. repo 本地已有配置 -> 保持不变
2. `PALIMPSEST_GIT_USER_NAME` / `PALIMPSEST_GIT_USER_EMAIL`
3. `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL`
4. 默认值：
   - `Palimpsest Agent`
   - `palimpsest@local.invalid`

这样：

- 普通 commit 路径可用
- `git commit --allow-empty` 路径也可用
- spawn child 的分析型任务不会因“无变更但需要空提交”而失败

## 影响

### Palimpsest

- `SpawnRequestData` 的 `tasks` 从 `list[dict]` 升级为显式结构
- `spawn()` 会：
  - 归一化 legacy payload
  - 自动填充父任务上下文能推断出的默认 job spec
- tool schema 不再把 `evo_root` 暴露给模型手填
- workspace 准备阶段自动补全 repo-local Git identity

### Trenni

- `_handle_spawn()` 改为消费 `prompt + job_spec`
- `supervisor.job.launched` 事件会带上 repo / init_branch / overrides，供后续 spawn 默认值继承与 replay 使用
- webhook 路径会推进 cursor
- poll fallback 采用“收到 webhook 后延迟下一次 poll”的规则
- event 处理幂等提升为统一的 `event.id` 级别

### Smoke Test 结果

实施前：

- 同一 child job 会被重复 launch
- child task 常因拿到空 prompt 而执行错误工作
- 空提交路径会因 git author identity 缺失失败

实施后：

- parent fan-out 只 launch `1 + 3` 次（1 parent + 3 children）
- child 可以拿到真实子任务语义并分别完成
- 空变更场景可稳定完成 publication

## 不采纳方案

### 不采纳 1: 只在 `_ready_queue` 或 `job_id` 层去重

原因：

- queue 会被消费，不能表达“这个 Pasloe event 是否已经执行”
- 同一 `event.id` 在 webhook 和 poll 两条路径重复进入时，队列状态不足以防重

### 不采纳 2: 只给 `job.spawn.request` 单独加 dedup，不推进 cursor

原因：

- 这只能修当前最明显的 spawn 重复问题
- webhook / polling 双路重复消费的根因仍在
- 其他事件类型未来仍可能遭遇同类问题

### 不采纳 3: 强制每个 child 都显式写完整 job spec

原因：

- 认知负担太高
- 大多数 child 任务本质上只是“在父任务同一 repo / branch / evo 上做更细分的 prompt”
- 默认值继承更符合常见使用模式

## 参考

- `docs/adr/0001-unified-spawn-model.md`
- `docs/adr/0004-quadlet-podman-job-runtime.md`
- `docs/adr/0004-three-layer-isolation-fork-correctness-git-auth.md`
