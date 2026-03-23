# ADR-0004: 暂停 Continuation、三层隔离解耦、环境优先 Git 认证

- **状态**: 已实施
- **日期**: 2026-03-23
- **决策者**: holo, Claude（架构评审 + 实施）
- **关联**: ADR-0001（统一 Spawn 模型）、ADR-0002（Yoitsu CLI）、ADR-0003（Quadlet 部署）

## 背景

基于 `docs/reviews/2026-03-22-architecture-review.md` 的发现，对 ADR-0001 实施后的代码进行了进一步评审和修复。发现四类问题：

1. **Continuation 机制尚不成熟**：ADR-0001 定义了 continuation（join side）的实现，但 fan-out（fork side）的基础正确性尚未验证——failed job 的依赖传播语义错误，drain-pause 交互有 bug。在 join 的前提条件不可靠时启用 continuation 是危险的。

2. **`isolation.py` 职责混杂**：`launch_job()` 同时承担环境准备和进程启动，`_build_job_env()` 硬编码了 API key 名称，evo symlink 在 isolation 层创建（本应属于 workspace 准备）。Layer 2（运行环境准备）和 Layer 3（agent 逻辑）的边界不清晰。

3. **Git 认证重复实现**：Trenni 的 `_build_job_env()` 和 Palimpsest 的 `workspace.py`/`publication.py` 都在做 token → HTTP header 转换。且 `publication.py` 有严重 bug：`repo.git.execute(env=auth_env)` 完全替换了进程环境（丢失 PATH、HOME 等）。

4. **Yoitsu CLI 零散改进**：ADR-0002 实施后积累了四项小改进需求。

## 决策

### 决策 1: 暂停 Continuation，仅保留 Fan-out

**采纳**。删除 continuation 代码，保留 `depends_on` 基础设施。

**具体变更**：
- 删除 `_handle_spawn` 中创建 continuation job 的代码路径
- 删除 `_build_continuation()` 方法
- 保留 `SpawnedJob.depends_on`、`_pending` 表、依赖解析逻辑（join 将来可重新启用）

**同时修复两个 fan-out 正确性 bug**：

#### Bug 1: Failed job 的依赖传播

原实现中 failed job 被加入 `_completed_jobs`，导致依赖它的 pending job 被释放进队列。这在语义上是错误的——依赖一个 failed job 的 job 不应被启动。

修复：
- 新增 `_failed_jobs: set[str]`
- Failed job 加入 `_failed_jobs` 而非 `_completed_jobs`
- Job 完成时扫描 `_pending`：如果 `depends_on` 中任一 job 在 `_failed_jobs`，则传播失败（发射 `job.failed` 事件，code: `dependency_failed`），而非释放进队列

#### Bug 2: Drain-pause 交互

`_drain_queue` 在容量不足时等待，但等待循环未检查 `_resume_event`（pause 标志），导致 pause 期间仍会在容量恢复后启动 job。

修复：容量等待循环加入 `self._resume_event.is_set()` 检查。

**理由**：
- Continuation 的前提是 fork 的依赖解析正确。先确保基础可靠，再构建上层
- `_failed_jobs` 语义比「failed 也算 completed」更正确
- 保留 `depends_on` 基础设施意味着重新启用 continuation 只需添加代码，无需重构

**变更文件**：`trenni/supervisor.py`、`trenni/tests/test_supervisor_queue.py`

---

### 决策 2: Trenni → Palimpsest 三层隔离解耦

**采纳**。将 `isolation.py` 的职责拆分为明确的三层。

**目标状态**：

```
Layer 1 (supervisor.py)   — 决定启动哪些 job（调度）
Layer 2 (isolation.py)    — 准备运行环境（workspace、env、git credential）
Layer 3 (palimpsest)      — agent 逻辑，假设本地权限已就绪
```

**具体变更**：

| 变更 | 说明 |
|------|------|
| 新增 `JobWorkspace` dataclass | 封装 `job_dir`、`config_path`、`env` |
| 新增 `prepare_workspace()` | 创建目录、evo symlink、写 config、构建 env dict |
| 新增 `launch_in_backend()` | 纯启动，接收 `JobWorkspace`，不做环境准备 |
| 重构 `_build_job_env()` | 接收 `env_keys: list[str]`，删除所有硬编码 key 名 |
| 新增 `_build_git_credential_env()` | 负责 token → `GIT_CONFIG_*` 环境变量转换 |

**理由**：
- `prepare_workspace()` + `launch_in_backend()` 替代原来的 `launch_job()`，职责清晰
- `_build_job_env()` 不再硬编码 key 名，通过配置驱动
- evo symlink 从 isolation 层移入 `prepare_workspace()`，属于 workspace 准备而非进程隔离

**变更文件**：`trenni/isolation.py`、`trenni/tests/test_isolation.py`

---

### 决策 3: 环境优先 Git 认证（Environment-First Git Auth）

**采纳**。Layer 2 负责注入 Git credential 环境变量，Layer 3 优先检查这些变量。

**机制**：

Layer 2（`isolation.py`）的 `_build_git_credential_env()` 将 token 转换为 Git 的
环境变量配置格式：

```
GIT_CONFIG_COUNT=1
GIT_CONFIG_KEY_0=http.extraHeader
GIT_CONFIG_VALUE_0=Authorization: Bearer <token>
```

这些变量通过 `prepare_workspace()` 注入 job 进程的环境。

Layer 3（Palimpsest）的 `workspace.py` 和 `publication.py` 采用 fallback 策略：

```python
if os.environ.get("GIT_CONFIG_COUNT"):
    # 运行环境已配置 credential，跳过 token 处理
    auth_env = {}
else:
    # Fallback：使用 config.yaml 中的 git_token_env 做 token→header 转换
    auth_env = _build_auth_env(config.git_token_env)
```

**同时修复 `publication.py` 的环境覆盖 bug**：

```python
# 修复前（丢失 PATH、HOME 等）：
repo.git.execute(env=auth_env)

# 修复后：
repo.git.execute(env={**os.environ, **auth_env})
```

**语义**：

| 场景 | Git credential 来源 |
|------|---------------------|
| 通过 Trenni 启动 | Layer 2 注入 `GIT_CONFIG_*`，Palimpsest fallback 不触发 |
| 独立运行 / 开发调试 | config.yaml 中设 `git_token_env`，Palimpsest 自行处理 |

**理由**：
- 消除 Trenni 和 Palimpsest 之间的重复 token→header 转换逻辑
- `GIT_CONFIG_*` 是 Git 原生支持的环境变量配置，无需额外工具
- Fallback 保证 Palimpsest 可独立运行，不强制依赖 Trenni

**变更文件**：`palimpsest/stages/workspace.py`、`palimpsest/stages/publication.py`

---

### 决策 4: Yoitsu CLI 四项改进

在 ADR-0002 基础上追加以下改进：

| 改进 | 变更 | 理由 |
|------|------|------|
| `_fail()` 类型标注 | 返回类型改为 `NoReturn`，`sys.exit(1)` → `raise SystemExit(1)` | 类型检查器能正确推断控制流 |
| URL 配置化 | `_PASLOE_URL`/`_TRENNI_URL` 可通过 `YOITSU_PASLOE_URL`/`YOITSU_TRENNI_URL` 覆盖 | Quadlet 部署中服务 URL 与开发环境不同 |
| PID 文件锁 | `acquire_lock()` 用 `fcntl.flock(LOCK_EX\|LOCK_NB)` 防止并发 `yoitsu up` | 两个 agent 同时执行 `up` 会导致 PID 文件损坏 |
| `up` 命令异步合并 | 提取 `_do_up()` async 函数，单次 `asyncio.run()` 调用 | 原实现多次 `asyncio.run()`，事件循环创建销毁开销不必要 |

**额外修复**：`start_pasloe`/`start_trenni` 子进程日志文件句柄不在父进程关闭，改用 `start_new_session=True` 实现进程分离。

**变更文件**：`yoitsu/cli.py`、`yoitsu/process.py`、`yoitsu/tests/test_cli.py`、`yoitsu/tests/test_process.py`

## 影响

### 变更范围

| 组件 | 变更 |
|------|------|
| `trenni/supervisor.py` | 删除 continuation、新增 `_failed_jobs`、修复 drain-pause |
| `trenni/isolation.py` | 三层拆分：`JobWorkspace` + `prepare_workspace()` + `launch_in_backend()` |
| `palimpsest/stages/workspace.py` | 环境优先 Git 认证 fallback |
| `palimpsest/stages/publication.py` | 环境优先 Git 认证 fallback + env 覆盖 bug 修复 |
| `yoitsu/cli.py` | URL 配置化、`_do_up()` 合并、`_fail()` 类型 |
| `yoitsu/process.py` | PID 文件锁、`start_new_session` |

### 向后兼容性

- Palimpsest 的 Git 认证 fallback 保证独立运行场景不受影响
- `SpawnedJob.depends_on` 保留，API 层面无变化
- Yoitsu CLI 命令接口不变，新增环境变量为可选

### 与其他 ADR 的关系

- **ADR-0001**：本 ADR 暂停了 ADR-0001 中决策 1 的 continuation 部分。fan-out 和 `_pending` 表保留。重新启用 continuation 应作为新的 ADR
- **ADR-0002**：本 ADR 的决策 4 是对 ADR-0002 实现的增量改进
- **ADR-0003**：三层隔离解耦（决策 2）和环境优先 Git 认证（决策 3）直接支持 ADR-0003 的 Quadlet 部署场景——`subprocess` backend 下 `prepare_workspace()` 准备的环境直接传给子进程

## 参考

- 架构评审: `docs/reviews/2026-03-22-architecture-review.md`
- ADR-0001: `docs/adr/0001-unified-spawn-model.md`
- ADR-0002: `docs/adr/0002-yoitsu-cli.md`
- ADR-0003: `docs/adr/0003-podman-quadlet-subprocess-deployment.md`
