# 0016: Capability 模型

## 1. 现状与存在的问题

ADR-0015 确立了 bundle 作为独立 git 仓库的架构，但没有定义 bundle 内部的运行时服务管理模型。当前的 `preparation_fn` / `finalization_fn` 绑定在 role 上，导致两个问题：

1. **fn 跨 role 重复**：Factorio bundle 中 `worker`、`evaluator`、`implementer` 都需要 RCON 连接，各自在 `preparation_fn` 中写相同的连接建立代码。
2. **准备与清理不对称**：有些 preparation 对应 publication（git clone → git commit+push），有些对应 cleanup（启动服务 → 停止服务），有些什么都不对应（拷贝脚本），但当前模型把它们混在一个 fn 中无法区分。

## 2. 做出的决策与原因

### 2a. Capability 是 bundle 提供的运行时服务管理单元

每个 capability 具有 `setup` + `finalize` 生命周期，自包含在一个模块中：

```python
class FinalizeResult:
    events: list[EventData]  # "做了什么"的事件数据
    success: bool            # 是否算成功（决定 job 终态）

class Capability(Protocol):
    name: str
    def setup(self, ctx: JobContext) -> list[EventData]: ...
    def finalize(self, ctx: JobContext) -> FinalizeResult: ...
```

- **内部完成实际工作**：副作用在函数体内发生（建立连接、commit+push、停止服务等）
- **返回事件数据 + success 标志**：events 描述"做了什么"，success 表示是否成功
- **Runtime 代发事件**：capability 对事件系统完全无感知
- **Runtime 根据 success 决定 job 终态**：全部 capability success=True → job.completed，任一 False → job.failed

**原因**：capability 只关心"做什么"和"回答做了什么"，不关心"怎么发事件"。这与 observation analyzer 只返回数据、Trenni 代发是同一个原则——事件发送是系统级关注点，不应泄漏到 bundle 代码中。

### 2b. Role 声明 capability 需求

Role 通过 `needs` 列表声明依赖哪些 capability。Runtime 在 preparation 阶段按列表实例化 capability 并调用 `setup()`，在 finalization 阶段调用 `finalize()`。

```python
metadata = RoleMetadata(
    name="worker",
    needs=["rcon_bridge", "script_sync"],
    contexts=["factorio_scripts"],
)
```

**原因**：capability 只写一次多 role 共享。`worker` 需要 `[rcon_bridge, script_sync]`，`evaluator` 只需要 `[rcon_bridge]`，复用而不重复。

### 2c. Capability 之间无排序依赖

如果两个动作有执行顺序要求，它们应该在同一个 capability 内处理。Capability 之间的 `finalize()` 互不依赖。

**原因**：排序 = 耦合。强制独立推动 bundle 作者把关联的生命周期管理放在一起，而不是散布在多个 capability 中。

### 2d. Finalize 合并了 publication 和 cleanup

不区分"publish"（有东西留下）和"teardown"（什么都不留）为独立阶段。"是否有东西留下"已经由返回的事件数据中是否包含 artifact ref 来表达——这就是 artifact 的语义。

**原因**：额外的阶段划分增加复杂性但不增加表达力。Capability 的 `finalize()` 返回什么，runtime 就记录什么。

### 2e. Context Provider 独立于 Capability

Context provider（LLM 上下文组装）不属于 capability 模型。两者正交：

| | Capability | Context Provider |
|---|---|---|
| **阶段** | preparation + finalization | context（setup 之后、agent loop 之前） |
| **消费者** | Runtime 生命周期管理 | LLM prompt 组装 |
| **是否发事件** | 是（通过返回值，runtime 代发） | 否 |
| **是否有副作用** | 是（启动服务、创建连接） | 否（只读查询 + 数据组装） |
| **输出去向** | 事件 → Event Store | 文本 → 注入 system/user prompt |

**原因**：Context provider 的设计初衷是把"查询 Pasloe"等信息组装逻辑作为可演化代码。它不管理生命周期、不发事件、只负责回答"LLM 这次需要知道什么"。混入 capability 会模糊生命周期管理和信息组装的边界。

### 2f. Finalize 错误处理：不允许抛异常，返回 success 标志

Finalize 是 job 的最后一道关口，**不允许抛出异常**。原因：

1. **副作用已完成**：git push、save world 等动作在 finalize 函数体内执行
2. **因果必须记录**：无论成功或失败，都必须返回事件数据，runtime 必 emit
3. **诊断需要信息**：失败原因必须记录在事件中

**实现要求**：每个 finalize 步骤必须有 try-catch 包裹，内部完成重试逻辑，最终返回 `(events, success)`：

```python
def finalize(self, ctx: JobContext) -> FinalizeResult:
    events = []
    success = True
    
    # 重试逻辑在 fn 内部完成
    MAX_RETRIES = 3
    for attempt in range(MAX_RETRIES):
        try:
            result = self._git_publish(ctx)
            events.append(EventData(type="artifact.published", data=result))
            break  # 成功，跳出重试
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                continue  # 重试
            # 重试耗尽
            events.append(EventData(type="finalize.failed", data={
                "capability": self.name,
                "stage": "git_publish",
                "error": str(e),
                "attempts": MAX_RETRIES,
                "artifact_persisted": False
            }))
            success = False
    
    # Cleanup（失败不影响 success）
    try:
        self._cleanup(ctx)
        events.append(EventData(type="cleanup.completed", data={"capability": self.name}))
    except Exception as e:
        events.append(EventData(type="cleanup.failed", data={
            "capability": self.name,
            "error": str(e)
        }))
    # cleanup 失败不改变 success 标志（artifact 已持久化）
    
    return FinalizeResult(events=events, success=success)
```

**Job 终态映射**：

Runtime 检查所有 capability 的 `success` 标志：

| 所有 capability success | job 终态 |
|---|---|
| 全部 True | `job.completed` |
| 任一 False | `job.failed` |

**关键原则**：

- **Artifact 持久化是核心**：`success=False` 表示 artifact 未成功持久化
- **Cleanup 失败不影响 success**：cleanup 是辅助动作，artifact 已持久化就算成功
- **重试在 fn 内部完成**：capability 自己决定重试策略

**Setup 失败处理不同**：Setup 失败 = job 立即失败，进入 preparation failure 路径，不进入 agent loop。

## 3. 期望达到的结果

- Bundle 内的运行时服务管理代码可共享、可组合、不重复
- Capability 对事件系统无感知，降低 bundle 代码的认知负担
- 准备与清理的对称性问题消失——每个 capability 自己管理自己的生命跨度

## 4. 容易混淆的概念

- **Capability vs Context Provider**
  - Capability 有生命周期（setup + finalize），管理运行时服务，可以有副作用
  - Context Provider 是一次性只读调用，为 LLM 组装上下文，无副作用
  - 两者正交：capability 服务于 runtime 生命周期，context 服务于 LLM prompt

- **Capability vs Tool**
  - Capability 在 agent loop 前后运行，管理基础设施
  - Tool 在 agent loop 中被 LLM 按需调用，完成具体任务动作
  - 一个 capability 可以为 tool 提供基础设施（如 `rcon_bridge` 为 `call_script` tool 提供连接）

- **Capability vs 共享 lib**
  - 共享 lib 是代码复用（函数调用），没有生命周期
  - Capability 是运行时服务管理（有 setup/finalize），有状态的连接、服务实例等用 lib 表达不自然

## 5. 对之前 ADR 或文档的修正说明

- 本 ADR 取代当前 role 定义中 `preparation_fn` / `finalization_fn` 的单一函数绑定模型。这些 fn 不再是 role 级别的概念，而是分解为 role 声明的 capability 列表。
- ADR-0012 中"RCON 桥接客户端作为 RuntimeContext 内管理的特殊资源"现在标准化为 `rcon_bridge` capability。
- ADR-0015 §2.3 的 bundle 目录结构新增 `capabilities/` 目录。
