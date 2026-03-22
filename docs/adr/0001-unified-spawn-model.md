# ADR-0001: 统一 Spawn 模型、Checkpoint 机制、Gateway 位置

- **状态**: 已实施
- **日期**: 2026-03-22
- **决策者**: 项目维护者 + Claude 架构评审

## 背景

Trenni supervisor 存在三个需要决策的架构问题：

1. **Spawn 与 ForkJoin 分离**：`task.submit` 走队列路径（入队 → drain → launch），`job.spawn.request` 走独立路径（直接 launch + ForkJoin 跟踪）。后者在容量不足时丢弃子任务，且 ForkJoin 是独立的跟踪结构，与队列/dedup 体系割裂。

2. **缺乏 Checkpoint**：所有内存状态在重启时丢失，replay 必须从头开始。已退出但未发终态事件的进程 slot 永久被占用。

3. **Gateway 位置**：每个 job subprocess 独立创建 LLM client 和 EventEmitter，是否应将 gateway 提升到 supervisor 层以避免重复创建？

## 决策

### 决策 1: 统一 Spawn 模型

**采纳**。用 `SpawnedJob` 统一替代 `TaskItem` + `ForkJoin`。

所有 job 创建本质上是 spawn，区别仅在于触发条件（`depends_on` 集合）：

| 场景 | depends_on |
|------|-----------|
| task.submit | 空（立即入队） |
| fork 子任务 | 空（立即入队） |
| join continuation | 所有子任务的 job_id |

**关键变更**：
- 删除 `ForkJoin` dataclass 和 `TaskItem` dataclass
- 新增 `SpawnedJob(depends_on: frozenset[str])`
- 依赖为空 → `_ready_queue`；依赖非空 → `_pending` 表
- job 完成时扫描 `_pending`，依赖满足自动入队
- Continuation 的 task 内容在依赖满足时从 `_job_summaries` 填充

**理由**：
- 消除子任务丢失的 bug
- 消除 continuation 在容量不足时丢失的 bug
- 单一代码路径，降低认知复杂度
- 自然扩展到更复杂的依赖模式（无需新增机制）

### 决策 2: Checkpoint + Reap

**采纳**。每 N 个 poll 周期（~60s）执行一次 checkpoint。

Checkpoint 做三件事：
1. **Reap**：进程退出超过 `reap_timeout`（120s）仍未收到终态事件 → 发射补偿 `job.failed` 事件并释放 slot
2. **锚点事件**：发射 `supervisor.checkpoint` 到 Pasloe，包含 cursor、运行中/pending 的 job 列表
3. **Replay 加速**：重启时先找最近 checkpoint 的 cursor，缩小 replay 范围

**关键变更**：
- `JobProcess` 增加 `exited_at: float | None` 字段
- `_reap_processes()` 改为 `_mark_exited_processes()`（仅标记退出时间）
- 新增 `_checkpoint()` 方法，在主循环中定期调用
- `_replay_unfinished_tasks()` 先查 `supervisor.checkpoint` 事件

**理由**：
- 解决进程崩溃导致 worker slot 永久被占的问题
- 补偿事件让依赖解析正常进行（而非永久阻塞）
- Checkpoint 减少长运行后重启的 replay 开销

### 决策 3: Gateway 不提升到 Supervisor

**不采纳**。Gateway 保留在 job subprocess 内。

**评估的两条路径**：

| 路径 | 做法 | 代价 |
|------|------|------|
| Job 变协程 | Gateway 共享 Python 对象 | 失去进程隔离、bubblewrap 沙箱、崩溃隔离 |
| 代理服务 | Trenni 运行 HTTP 代理 | 增加故障面、IPC 复杂度、bubblewrap 兼容问题 |

**收益分析**：

- LLM client 创建开销 < 1ms，相比 LLM API 调用延迟（秒级）可忽略
- Event 发射路径已通过 Pasloe 集中化，再加代理是冗余间接层
- Token/成本追踪可在事件流上完成（`LLMResponseData` 已包含 token 计数）
- 唯一有实质价值的收益是跨 job rate limit 协调

**替代方案**：rate limit 协调通过 `_drain_queue` 中的 `launch_stagger` 实现（job 间延迟启动），无需改变架构。

**理由**：
- Job 作为自包含 subprocess 是核心架构原则（进程隔离、bubblewrap 沙箱、崩溃隔离）
- 收益微弱，代价不对称
- 保持 job 的可独立运行性（只需 YAML config + 环境变量）

## 影响

### 变更范围

| 组件 | 变更 |
|------|------|
| `trenni/supervisor.py` | 重写：统一 spawn + checkpoint |
| `trenni/isolation.py` | `JobProcess` 增加 `exited_at` 字段 |
| `trenni/tests/` | 全部重写，29 个测试 |
| Palimpsest | 无变更 |
| Pasloe | 无变更（新增 `supervisor.checkpoint` 事件类型，但 Pasloe 是 schema-agnostic 的） |

### 向后兼容性

- `SpawnRequestData` 事件格式不变，Palimpsest 侧零修改
- `task.submit` 事件格式不变，提交脚本零修改
- `supervisor.job.launched` 事件格式不变

### 风险

- `_completed_jobs` 集合在长运行中持续增长。当前可接受（UUID 字符串，每个 ~36 字节），未来可按 checkpoint 周期截断
- `_job_summaries` 同理。可在 checkpoint 时清理已无 pending 依赖的 entry

## 参考

- 设计文档: `docs/superpowers/specs/2026-03-22-unified-spawn-checkpoint-design.md`
- 架构评审: `docs/reviews/2026-03-22-architecture-review.md`
