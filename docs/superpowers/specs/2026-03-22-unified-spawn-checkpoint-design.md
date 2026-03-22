# Unified Spawn Model + Checkpoint 设计

## 问题陈述

当前 Trenni 的任务调度存在两个独立机制：

1. **task.submit** → `_handle_task_submit` → 入队 → drain 消费
2. **job.spawn.request** → `_handle_spawn` → 直接 launch（容量不足则丢弃）+ ForkJoin 跟踪

这导致：
- Spawn 子任务在容量不足时丢失
- ForkJoin 是独立的跟踪结构，与队列/dedup 体系割裂
- `_resolve_fork_join` 中 continuation 也可能因容量不足而丢失
- 两条代码路径做本质上相同的事——"决定何时可以启动一个 job"

同时，`_reap_processes` 不清理已退出进程的 slot，且缺乏 checkpoint 机制导致每次重启必须全量 replay。

## 核心洞察

**所有 job 的创建本质上都是 spawn。区别仅在于触发条件。**

| 场景 | 触发条件 |
|------|---------|
| `task.submit` | 无条件（立即可入队） |
| fork 部分的子 job | 无条件（立即可入队） |
| join 部分的 continuation job | 依赖一组 job 全部完成 |

ForkJoin 不是独立概念，而是 spawn 的一种模式：spawn N+1 个 job，其中 N 个无条件，1 个有依赖条件。

---

## 方案：统一 Spawn 模型

### 数据模型

```python
@dataclass
class SpawnedJob:
    """一个已被 supervisor 认领的 job，可能还在等待依赖。"""
    job_id: str
    source_event_id: str   # 触发此 job 的事件 ID
    task: str
    role: str
    repo: str
    init_branch: str
    evo_sha: str | None
    depends_on: frozenset[str] = frozenset()  # 需要等待完成的 job_id 集合
```

`depends_on` 为空 → 立即入队等待容量。
`depends_on` 非空 → 存入 pending 表，等依赖满足后入队。

### Supervisor 状态

```python
class Supervisor:
    # 替代原有的 fork_joins + _task_queue
    _ready_queue: asyncio.Queue[SpawnedJob]       # 依赖已满足，等待容量
    _pending: dict[str, SpawnedJob]               # job_id → 等待依赖的 job
    _completed_jobs: set[str]                     # 已完成的 job_id（用于依赖检查）
    _launched_event_ids: set[str]                 # dedup guard（不变）
    jobs: dict[str, JobProcess]                   # 运行中的进程（不变）
```

删除 `ForkJoin`、`TaskItem`。统一为 `SpawnedJob`。

### 事件处理

#### task.submit

```python
async def _handle_task_submit(self, event: Event) -> None:
    if event.id in self._launched_event_ids:
        return
    self._launched_event_ids.add(event.id)

    job = SpawnedJob(
        job_id=self._generate_job_id(),
        source_event_id=event.id,
        task=data["task"],
        role=data.get("role", "default"),
        ...
        depends_on=frozenset(),  # 无依赖，立即可执行
    )
    await self._enqueue(job)
```

#### job.spawn.request

```python
async def _handle_spawn(self, event: Event) -> None:
    parent_job_id = data["job_id"]
    tasks = data["tasks"]
    wait_for = data.get("wait_for", "all_complete")

    child_ids = []
    for i, child_def in enumerate(tasks):
        child_id = f"{parent_job_id}-c{i}"
        child_ids.append(child_id)
        child = SpawnedJob(
            job_id=child_id,
            source_event_id=event.id,
            ...,
            depends_on=frozenset(),  # 子 job 无依赖
        )
        await self._enqueue(child)

    # continuation job 依赖所有子 job
    continuation = SpawnedJob(
        job_id=f"{parent_job_id}-join",
        source_event_id=event.id,
        task="",  # 由 _build_continuation_task() 在依赖满足时填充
        role="default",
        ...,
        depends_on=frozenset(child_ids),
    )
    self._pending[continuation.job_id] = continuation
```

#### 统一入队

```python
async def _enqueue(self, job: SpawnedJob) -> None:
    """根据依赖状态决定入队还是挂起。"""
    unsatisfied = job.depends_on - self._completed_jobs
    if not unsatisfied:
        await self._ready_queue.put(job)
    else:
        self._pending[job.job_id] = job
```

#### job.completed / job.failed

```python
async def _handle_job_done(self, event: Event) -> None:
    job_id = event.data.get("job_id", "")
    self.jobs.pop(job_id, None)
    self._completed_jobs.add(job_id)

    # 扫描 pending，检查是否有 job 的依赖被满足
    newly_ready = []
    for pending_id, pending_job in list(self._pending.items()):
        unsatisfied = pending_job.depends_on - self._completed_jobs
        if not unsatisfied:
            # 如果是 continuation，此时填充 task 内容
            if not pending_job.task:
                pending_job = self._build_continuation(pending_job)
            newly_ready.append(pending_id)
            await self._ready_queue.put(pending_job)

    for jid in newly_ready:
        del self._pending[jid]
```

### Continuation 构建

```python
def _build_continuation(self, job: SpawnedJob) -> SpawnedJob:
    """从已完成子 job 的事件中组装 continuation task 内容。"""
    # 从 _completed_jobs 和事件记录中获取子 job summary
    # 这里可以用 _job_summaries: dict[str, str] 在 _handle_job_done 时缓存
    child_summaries = []
    for child_id in sorted(job.depends_on):
        summary = self._job_summaries.get(child_id, "(no summary)")
        child_summaries.append(f"- {child_id}: {summary}")

    return dataclasses.replace(job, task=(
        "Continue after child tasks completed.\n\n"
        "Child results:\n" + "\n".join(child_summaries)
    ))
```

### Drain 不变

`_drain_queue` 从 `_ready_queue` 消费，逻辑与当前相同——等容量后 launch。

---

## 方案：Checkpoint + Reap

### 设计原则

Checkpoint 是一个**定期执行的维护操作**，做三件事：
1. 扫描进程状态，清理已退出的进程 slot
2. 序列化内存状态到事件流（作为锚点）
3. 记录 cursor 位置，使下次重启 replay 更快

### 触发时机

在主循环中，每 N 个 poll 周期执行一次（例如每 60 秒）：

```python
async def _run_loop(self) -> None:
    polls_since_checkpoint = 0
    while self.running:
        await self._poll_and_handle()
        polls_since_checkpoint += 1

        if polls_since_checkpoint >= self._checkpoint_interval:
            await self._checkpoint()
            polls_since_checkpoint = 0

        await asyncio.sleep(self.config.poll_interval)
```

### Checkpoint 逻辑

```python
async def _checkpoint(self) -> None:
    """定期维护：扫描进程、清理 slot、发射锚点事件。"""
    # 1. Reap: 扫描已退出进程
    now = time.monotonic()
    for job_id, jp in list(self.jobs.items()):
        if jp.proc.returncode is not None:
            age = now - jp.exited_at  # 记录首次发现退出的时间
            if age > self.config.reap_timeout:  # 例如 120 秒
                logger.warning(
                    "Job %s process exited %ds ago without terminal event, "
                    "emitting compensating failure",
                    job_id, int(age),
                )
                await self.client.emit("job.failed", {
                    "job_id": job_id,
                    "error": f"Process exited (rc={jp.proc.returncode}) without emitting terminal event",
                    "code": "process_lost",
                })
                del self.jobs[job_id]

    # 2. Emit checkpoint event (锚点)
    await self.client.emit("supervisor.checkpoint", {
        "cursor": self.event_cursor,
        "running_jobs": list(self.jobs.keys()),
        "pending_jobs": list(self._pending.keys()),
        "ready_queue_size": self._ready_queue.qsize(),
        "completed_count": len(self._completed_jobs),
    })
```

### Replay 优化

重启时，先查找最近的 `supervisor.checkpoint` 事件，从其 cursor 开始 replay，而非全量 replay：

```python
async def _replay_unfinished_tasks(self) -> None:
    # 尝试从最近 checkpoint 恢复
    checkpoints = await self._fetch_all(
        "supervisor.checkpoint", source=self.config.source_id
    )
    if checkpoints:
        latest_cp = checkpoints[-1]
        self.event_cursor = latest_cp.data.get("cursor")
        logger.info("Resuming from checkpoint (cursor=%s)", self.event_cursor)

    # 然后只 replay checkpoint 之后的事件
    # ... 现有 replay 逻辑，但范围缩小到 checkpoint 之后
```

### `_reap_processes` 改造

原有的 `_reap_processes` 改为只记录退出时间，不做清理：

```python
def _mark_exited_processes(self) -> None:
    """标记已退出进程的退出时间，由 checkpoint 负责清理。"""
    for job_id, jp in self.jobs.items():
        if jp.proc.returncode is not None and jp.exited_at is None:
            jp.exited_at = time.monotonic()
            logger.info("Process for job %s exited (rc=%d)", job_id, jp.proc.returncode)
```

`JobProcess` 增加 `exited_at: float | None = None` 字段。

---

## 变更摘要

### 删除
- `ForkJoin` dataclass
- `TaskItem` dataclass
- `_handle_spawn` 中的直接 launch 逻辑
- `_resolve_fork_join`
- `fork_joins` dict
- 独立的 `_reap_processes`

### 新增
- `SpawnedJob` dataclass（统一 TaskItem + ForkJoin 子任务 + continuation）
- `_pending: dict[str, SpawnedJob]`（等待依赖的 job）
- `_completed_jobs: set[str]`
- `_job_summaries: dict[str, str]`（缓存完成 job 的 summary）
- `_ready_queue`（替代 `_task_queue`）
- `_enqueue()` — 统一入队，自动判断依赖
- `_build_continuation()` — 从子 job 结果构建 continuation task
- `_checkpoint()` — 定期维护
- `_mark_exited_processes()` — 标记退出时间
- `JobProcess.exited_at` 字段

### 修改
- `_handle_task_submit` → 使用 SpawnedJob + _enqueue
- `_handle_spawn` → 创建 N+1 个 SpawnedJob，children 无依赖，continuation 有依赖
- `_handle_job_done` → 记录完成 + 扫描 pending 解除依赖
- `_run_loop` → 增加 checkpoint 周期
- `_replay_unfinished_tasks` → 先查 checkpoint 锚点，缩小 replay 范围

### 不变
- `_drain_queue` 逻辑不变（队列名从 `_task_queue` 改为 `_ready_queue`）
- `_launch` 逻辑不变
- `_has_capacity` 不变
- Palimpsest 侧的 `SpawnRequestData` 不变
- 事件格式不变（`task.submit`, `job.spawn.request` 的 payload 不变）

---

## 架构影响

### Palimpsest 侧
**无变更**。`SpawnRequestData` 的格式和语义保持不变。Agent 仍然只发射 spawn request，不关心调度细节。

### Pasloe 侧
**无变更**。新增 `supervisor.checkpoint` 事件类型，但 Pasloe 是 schema-agnostic 的，无需任何修改。

### Trenni 侧
**仅 `supervisor.py`**。变更集中在数据模型和事件处理器中，isolation/config/cli 不受影响。

---

## 附录：Gateway 提升到 Supervisor 的评估

### 背景

评估是否应将 Palimpsest 中的 LLM Gateway / Event Gateway 提升到 Trenni supervisor 层，以避免每个 job subprocess 重复创建 client。

### 当前状态

每个 job 是独立 subprocess，各自创建：
- `EventEmitter` — httpx.Client → Pasloe
- `UnifiedLLMGateway` — 每次 `call()` 创建 OpenAI/Anthropic SDK client
- `UnifiedToolGateway` — 加载 evo 工具

### 实现路径

| 路径 | 方式 | 代价 |
|------|------|------|
| A: Job 变协程 | Gateway 成为共享 Python 对象 | 失去进程隔离、bubblewrap 沙箱、崩溃隔离 |
| B: 代理服务 | Trenni 运行 HTTP 代理，job 通过 localhost 连接 | 增加故障面、IPC 复杂度、bubblewrap 下可能无法访问 |

### 逐项收益分析

| 维度 | 收益 | 评估 |
|------|------|------|
| LLM client 复用 | 避免每 job 创建 SDK client | SDK client 初始化 < 1ms，相比 LLM 调用延迟（秒级）可忽略 |
| Rate limit 协调 | 并发 job 共享 API key 统一排队 | **唯一有实质价值的收益**，但当前 retry_utils 已处理 429 |
| 连接池 | 持久连接复用 | LLM 调用频率低，连接建立开销微不足道 |
| Token/成本追踪 | 集中统计 | `LLMResponseData` 事件已发到 Pasloe，可在事件流上完成 |
| Event 发射 | 减少 HTTP 连接数 | Pasloe 已是集中式 event gateway，再加一层是冗余间接 |

### 结论：不采纳

1. **收益微弱**。唯一有意义的收益是 rate limit 协调
2. **代价不对称**。路径 A 破坏进程隔离；路径 B 引入新故障面
3. **违反 "job 是自包含单元" 原则**。当前 job 只需 YAML + 环境变量即可运行

**Rate limit 协调的替代方案**：在 `_drain_queue` 中加入 `launch_stagger`（例如 0.5s），避免并发 job 同时首次调用 LLM，无需改变架构。
