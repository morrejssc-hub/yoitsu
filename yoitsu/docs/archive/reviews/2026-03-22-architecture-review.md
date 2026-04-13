# Yoitsu 项目架构评审

> 日期: 2026-03-22
> 范围: palimpsest, palimpsest-evo, trenni, pasloe, yoitsu
> 关注点: 架构功能、代码简洁性、组件解耦、职责清晰度

---

## 一、整体评价

这是一个设计良好的自演化 Agent 系统，架构原则清晰：

- **骨骼/肌肉分离** — Runtime 不可变，evo 可自由演化
- **事件溯源** — Git + Event Stream 作为唯一真实数据源
- **三层权限** — Locked / Stable / Free
- **Fork-Join** 作为唯一编排原语

四个组件的职责边界基本正确：Pasloe 只管事件存储，Trenni 只管调度，Palimpsest 只管执行，Evo 只管可演化内容。

但在实际代码层面，存在若干**解耦不彻底、死代码、职责越界**的问题。以下按严重程度排列。

---

## 二、关键问题

### P0: palimpsest-evo 存在大量无法运行的死代码

**问题**: evo 中存在两套实现模式并存——但只有一套能实际工作。

**装饰器模式（能工作）**:
- `contexts/loaders.py` — 使用 `@context_provider` 装饰器
- `tools/file_tools.py` — 使用 `@tool` 装饰器
- `tools/task_complete.py` — 使用 `@tool` 装饰器

**类模式（完全无法工作）**:
- `contexts/file_tree_provider.py` — 导入不存在的 `palimpsest.runtime.interfaces.ContextProvider`
- `contexts/task_description_provider.py` — 同上
- `contexts/recent_events_provider.py` — 同上
- `contexts/version_history_provider.py` — 同上
- `tools/file_ops.py` — 导入不存在的 `palimpsest.runtime.interfaces.ToolProvider` 和 `palimpsest.gateway.tools.ToolResult`

**原因**: Palimpsest runtime 只实现了装饰器加载机制（`contexts.py:_load_context_functions` 扫描 `__is_context__`，`tools.py:_load_tool_functions` 扫描 `__is_tool__`），从未实现 `interfaces` 模块或 `gateway` 包。类模式的文件是早期设计的残留，从未被连接到 runtime。

**影响**:
- evo 仓库中一半的文件是死代码
- `file_ops.py` 有路径遍历防护，`file_tools.py` 没有——但实际运行的是后者
- 新开发者会困惑该用哪套模式

**建议**: 删除所有类模式文件，只保留装饰器模式。如果需要路径遍历防护，在 `file_tools.py` 中加入。

---

### P0: palimpsest-evo 存在冗余的 YAML 配置

**问题**: `contexts/default.yaml` 定义了 context sections（包含 `recent_events`），但 runtime 实际从 `roles/default.py` 的 `RoleDefinition.contexts` 读取配置。YAML 文件从未被加载。

两者内容还不一致——YAML 包含 `recent_events`，Python role 不包含。

**建议**: 删除 `contexts/default.yaml`。Context 配置应且只应在 Role 定义中声明。

---

### P1: Trenni spawn 处理器在容量不足时丢弃子任务

```python
# supervisor.py:245-248
if self._has_capacity():
    await self._launch(child_id, ...)
else:
    logger.info("At capacity, cannot launch child %s", child_id)
```

spawn 的子任务没有入队，直接 log 后丢弃。但 ForkJoin 仍然记录了这些 child_ids，导致 fork-join 永远无法 resolve。

**对比**: `task.submit` 正确地使用了 `_task_queue` 入队。Spawn 应该走同样的路径。

**建议**: Spawn 的子任务也应封装为 TaskItem 入队。

---

### P1: Trenni `_reap_processes` 不清理已退出进程

```python
# supervisor.py:492-503
def _reap_processes(self):
    for job_id, jp in list(self.jobs.items()):
        if jp.proc.returncode is not None:
            logger.info("Process for job %s exited (rc=%d)", ...)
            # Don't remove from self.jobs here — wait for the
            # authoritative job.completed/job.failed event from Pasloe.
```

设计意图是等 Pasloe 事件来删。但如果进程崩溃前未发出事件（比如 OOM kill），这个 slot 永久被占。`_has_capacity()` 永远多计一个。

**建议**: 增加超时检测——进程退出后 N 秒仍未收到终态事件，则强制清理并发补偿事件。

---

### P1: Trenni `_resolve_fork_join` 查询效率极低

```python
# supervisor.py:288-300
for child_id in fj.child_ids:
    events, _ = await self.client.poll(source=self.config.default_eventstore_source)
    for ev in events:
        if ev.data.get("job_id") == child_id and ev.type == "job.completed":
            ...
```

对每个 child 都发一次无 type 过滤的 poll，然后在客户端遍历。应该用 `_fetch_all("job.completed")` 一次查完。

---

### P2: LLM client 每次调用都重新创建

```python
# llm.py:126-129 (_call_openai)
client = openai.OpenAI(
    api_key=self._api_key or os.environ.get("OPENAI_API_KEY"),
    base_url=self._config.api_base if self._config.api_base else None,
)
```

Anthropic 侧同理。SDK client 应在 `__init__` 中创建一次并复用。

---

### P2: Palimpsest `UnifiedToolGateway` 的 gateway 注入有隐式安全边界

```python
# tools.py:303
if "gateway" in sig.parameters and getattr(func, "__module__", "").startswith("palimpsest.runtime"):
    kwargs["gateway"] = self._gateway
```

evo 工具即使签名中声明 `gateway` 参数，也不会被注入。这是**正确的安全边界**（防止 evo 代码直接发射事件），但完全没有文档或错误提示。evo 开发者写了 `gateway` 参数会静默收到 KeyError。

**建议**: 在 `_load_tool_functions` 时检查 evo 工具是否声明了禁止的参数名，给出明确警告。

---

## 三、架构层面的改进建议

### 3.1 消除 evo 中的双模式

当前 evo 同时存在：
- 装饰器函数模式（runtime 实际支持）
- 类/接口模式（runtime 不支持，导入会报错）

**建议**: 只保留装饰器模式。它更简洁、更 Pythonic、与 runtime 的动态加载机制天然匹配。如果未来需要有状态的 provider，可以在装饰器函数中使用闭包。

### 3.2 Palimpsest 的 context 注入应更显式

当前 `build_context()` 通过 `inspect.signature` 探测函数参数来决定注入什么：

```python
if "workspace" in sig.parameters:
    kwargs["workspace"] = workspace_path
if "task" in sig.parameters:
    kwargs["task"] = task
```

工具侧也用同样的模式。这种「按名字匹配」的隐式注入容易出错（参数重名、拼写错误无提示）。

**建议**: 定义一个小的 `RuntimeContext` dataclass，context provider 和 tool 通过一个显式的 `ctx` 参数接收它：

```python
@context_provider("file_tree")
def file_tree(ctx: RuntimeContext, max_files: int = 100) -> str:
    ...  # ctx.workspace, ctx.job_id, ctx.task
```

### 3.3 Pasloe store 层的 `query_events` 参数过多

```python
async def query_events(
    db, *, event_id, source, type_, since, until,
    cursor, limit, order, projection_filters, projection_registry,
) -> ...
```

11 个参数。可以引入 `EventQuery` dataclass 来封装查询条件，减少参数传递。

### 3.4 Trenni supervisor 应拆分事件处理

`supervisor.py` 516 行，同时承担：
- 事件轮询
- 任务入队
- Spawn/Fork-Join
- Replay
- 进程管理

事件处理器（`_handle_task_submit`, `_handle_spawn`, `_handle_job_done`）可以提取为独立的 handler 类或函数，supervisor 只负责调度。

---

## 四、各组件职责清晰度评估

| 组件 | 职责清晰度 | 说明 |
|------|-----------|------|
| **Pasloe** | ★★★★★ | 纯粹的事件存储。API 薄层 → store 逻辑层 → DB 层，分层干净。Projection 系统设计优雅。 |
| **Palimpsest** | ★★★★☆ | 四阶段流水线清晰。扣分点：LLM gateway 承担了协议转换 + 重试 + 事件发射三重职责，可以再拆。 |
| **Trenni** | ★★★☆☆ | 核心调度逻辑正确，但 spawn 和 fork-join 的实现有 bug，replay 逻辑和主循环耦合较紧。 |
| **Palimpsest-evo** | ★★☆☆☆ | 死代码占一半，双模式混乱。需要大幅清理后才能成为自演化的良好起点。 |
| **Yoitsu** | ★★★★☆ | 脚本和配置角色清晰。扣分点：`config/trenni.yaml` 中的路径是硬编码的绝对路径。 |

---

## 五、代码简洁性评估

### 值得肯定的设计

1. **Role → JobSpec 展开后丢弃 role 引用** — runtime 只看 JobSpec，角色名仅供日志。消除了 runtime 对 role 的依赖。

2. **`@tool` 装饰器自动生成 JSON Schema** — 从函数签名和类型提示推导，零样板代码。

3. **Publication guardrail 的 recovery 机制** — 不重启 job，而是注入 user message 让 agent 自行修复，保留对话上下文。

4. **Pasloe 的 two-phase query** — Phase 1 在事件表查，Phase 2 在 projection 表过滤，cursor 基于 Phase 1 计算。优雅地解耦了核心查询和加速结构。

5. **Isolation backend 的 Protocol 模式** — SubprocessBackend / BubblewrapBackend 通过 Protocol 类型约束，无需基类继承。

### 需要简化的地方

1. **`_call_anthropic` 中的消息压缩逻辑** (llm.py:260-272) — 30 行用于处理 Anthropic 的「不允许连续相同 role」限制。应提取为独立函数 `compress_messages()`。

2. **Trenni `_replay_unfinished_tasks`** (supervisor.py:339-433) — 95 行的 replay 逻辑，5 次 `_fetch_all` 调用。应拆为独立模块 `replay.py`。

3. **`bash_with_config` 闭包包装** (tools.py:260-264) — 为了给 bash 注入 config 而创建闭包包装。更好的做法是让 `execute()` 统一注入 config。

---

## 六、具体行动项（按优先级）

### 立即执行

| # | 组件 | 行动 |
|---|------|------|
| 1 | palimpsest-evo | 删除 `tools/file_ops.py`，在 `file_tools.py` 中增加路径遍历防护 |
| 2 | palimpsest-evo | 删除 `contexts/file_tree_provider.py`, `task_description_provider.py`, `recent_events_provider.py`, `version_history_provider.py` |
| 3 | palimpsest-evo | 删除 `contexts/default.yaml` |
| 4 | trenni | 修复 `_handle_spawn`: 子任务入队而非直接 launch-or-drop |
| 5 | trenni | 在 `_reap_processes` 中增加超时清理机制 |

### 短期改进

| # | 组件 | 行动 |
|---|------|------|
| 6 | palimpsest | LLM client 在 `__init__` 中创建并缓存 |
| 7 | palimpsest | 提取 `compress_messages()` 为独立函数 |
| 8 | trenni | `_resolve_fork_join` 改用批量查询 |
| 9 | trenni | 提取 replay 逻辑到独立模块 |
| 10 | palimpsest | 对 evo 工具声明禁止参数名时给出明确警告 |

### 长期考虑

| # | 组件 | 行动 |
|---|------|------|
| 11 | palimpsest | 引入 `RuntimeContext` dataclass 替代按名注入 |
| 12 | pasloe | 引入 `EventQuery` dataclass 简化 `query_events` 签名 |
| 13 | yoitsu | `config/trenni.yaml` 使用相对路径或环境变量 |

---

## 七、总结

项目的顶层架构设计是优秀的——骨骼/肌肉分离、事件溯源、fork-join 原语，这些选择正确且互相一致。Pasloe 作为最简单的组件，代码质量最高。Palimpsest 的四阶段流水线和 guardrail recovery 设计精巧。

最大的问题在 **palimpsest-evo**——作为「可演化肌肉」，它本身充满了无法运行的死代码和两套互斥的设计模式。这直接威胁自演化的可行性：如果 agent 试图基于类模式文件来演化，结果一定是失败的。

其次是 **trenni** 的 spawn 路径有逻辑漏洞（子任务丢失、进程 slot 泄漏），需要尽快修复以确保 fork-join 的可靠性。

清理 evo 死代码、修复 trenni spawn——这两项做完后，系统就具备了可靠运行和自演化的基础。
