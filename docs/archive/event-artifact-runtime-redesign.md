# 事件与产物双真实源的运行时转向

日期：2026-04-01
状态：架构转向说明，非 ADR

## 1. 目的

这份文档记录一次重大架构转向：

- 不再把 `workspace`、进程内返回值、git 分支视为天然真实源。
- 将系统真相收敛到两类对象：
  - `event store`：记录“发生了什么”
  - `artifact store`：记录“产出了什么物理对象”
- 将执行器收缩为短命、边界清晰的单次 `attempt runner`。
- 将任务级连续性、下一步决策、重试/验证/发布判断上移到控制面。

这不是对现有四阶段流水线的小修，而是运行时本体的重新定义，因此不放入 ADR 序列，先作为根目录架构说明保存。

## 2. 当前问题

现有模型仍然带有明显的 `workspace/git` 中心惯性：

- `workspace` 容易被误当成真实源，而它本质上只是当前 job 的本地物化层。
- `publication` 容易被缩窄为 git commit / push / PR，而真实外部任务的输出并不一定是 git 产物。
- 进程内函数返回值承载了过多语义，但这些语义在重启后并不可恢复。
- 非 git-native 任务必须绕路伪装成 repo 任务。
- 执行器、调度器、事件系统之间的“真相边界”不够清晰。

## 3. 核心判断

### 3.1 双真实源

系统真实源只存在于两处：

1. `event store`
   - 记录任务生命周期、观察、失败、验证、发布决策、attempt 边界
2. `artifact store`
   - 保存输入、输出、快照、报告、目录树、bundle 等物理对象

其他一切都降级为派生层或加速层：

- `workspace`
- `runtime memory`
- `git branch`
- 临时缓存

### 3.2 单任务 loop 不是长活 actor

`single-task agent loop` 应理解为：

- 一次 attempt 的执行原子
- 一个短命、一次性的 job
- 一个可以忠实失败的执行过程

它不应承担：

- 长期任务真相持有
- 任务级重放
- 复杂恢复
- 下一步调度决策

### 3.3 事件驱动决策循环属于控制面

新的主抽象不是固定的 `preparation -> context -> interaction -> publication`，而是：

1. 由控制面从事件流投影出 `TaskView`
2. 基于 `TaskView` 选择下一次 `attempt` 或 `effect`
3. 执行器执行单次 attempt
4. 将过程和结果写回事件与产物
5. 控制面继续投影并决定下一步

四阶段最多保留为某类任务的默认执行 profile，不应继续作为运行时内核本体。

## 4. 新模型

推荐模型：

`事件驱动控制面 + 内容寻址 artifact 平面 + 短命执行平面`

### 4.1 各层职责

#### 控制面

负责：

- 归约 task state
- 维护任务级决策循环
- 判断是否需要新的 agent / validator / publisher attempt
- 生成 `attempt planned` 类事件
- 处理重试、继续执行、验证、完成判定

不负责：

- 持有工作区
- 直接执行工具
- 直接跑模型

#### Artifact 平面

负责：

- 存储不可变物理对象
- 提供内容寻址引用
- 支持重建 workspace
- 支持 bundle / tree / blob 级别对象

不负责：

- 高层业务语义解释

#### 执行平面

负责：

- 读取已规划好的 attempt 契约
- 拉取 artifact refs
- 物化本次本地 workspace
- 运行单次 agent / validator / publisher attempt
- 产出事件和 artifacts

不负责：

- 任务级调度
- 任务级重试决策
- 长活编排

## 5. Artifact Store

## 5.1 最小支持对象类型

第一版建议支持：

- `blob`
  - 不可变字节串
- `tree`
  - 目录树快照
- `bundle`
  - 多对象封装，适合一个任务包、一个报告包、一个 checkpoint 包

可选扩展：

- `git-pack`
- `git-object-set`

但它们只是物理格式兼容，不应上升为中心抽象。

## 5.2 `ArtifactRef` 只表达物理属性

`ArtifactRef` 不应携带高层语义标签。

建议最小字段集合：

```text
ArtifactRef {
  store_id
  object_kind   // blob | tree | bundle | optional extensions
  digest
  size_bytes
  encoding      // optional: raw, gzip, tar, zip, git-pack ...
}
```

如果未来需要增加字段，也只应增加物理相关内容，例如：

- 哈希算法
- 压缩方式
- 是否保留 symlink / mode bit
- 存储后端信息

不应增加：

- `task_domain`
- `publishable_output`
- `workspace_seed`
- `checkpoint`
- `git_repo_for_code_task`

## 5.3 为什么不要把语义塞进 ref

原因有四个：

1. 同一物理对象在不同任务里可以承担不同角色。
2. 高层语义是演化的，物理标识不应随业务命名变化而漂移。
3. 把语义塞进 ref 会把 ref 变成半状态对象，降低复用性。
4. 真正决定一个对象“是什么”的，不是 ref 自己，而是“谁在什么事件里、以什么关系引用它”。

## 5.4 事件如何解释 ref

语义解释放在事件层。

事件 payload 不直接给“有语义的 ref”，而是给：

```text
ArtifactBinding {
  ref
  relation
  path
  mode
  provenance
}
```

例如：

- `relation=workspace_root`
- `relation=read_only_input`
- `relation=validator_report`
- `relation=publish_candidate`
- `relation=save_checkpoint`

这样：

- `ref` 保持物理稳定
- 语义由事件解释
- 同一个 `tree ref` 既可以被当成普通目录，也可以在具备 `.git` 物理内容时被解释为 git repo

## 6. `TaskView` 与 `workspace` 的区别

### 6.1 `TaskView`

`TaskView` 是从事件流和 artifact metadata 投影出的任务决策视图。

它应包含：

- 当前任务目标
- 输入引用
- 关键观察
- 已产出的 artifacts
- 最近失败 attempt 的错误类别
- 当前未决事项
- 当前预算或尝试状态
- continuation hints

它是“为了决定下一步做什么”的结构化状态。

### 6.2 `workspace`

`workspace` 是为某次 attempt 临时物化出来的本地目录。

它应当：

- 可丢弃
- 可重建
- 不承担任务级真实源职责
- 只服务本次执行

一句话总结：

- `TaskView` 是决策视图
- `workspace` 是执行物化层

## 7. 执行器应如何变化

执行器应从“拥有完整 job pipeline 的 runtime”转成“单次 attempt runner”。

### 7.1 新输入

执行器输入不应再是“请自行推导完整状态”的任务，而应是明确的 `RunAttempt` 契约：

- attempt id
- task id
- 本次输入 artifact bindings
- context 选择规则
- prompt / context refs
- tools / runtime profile
- validation / publication 要求

### 7.2 新输出

执行器输出只有两类：

1. 事件
2. artifacts

进程返回值只用于当前 attempt 内部控制流，不再承载长期语义。

### 7.3 轻量失败仍然是合理目标

这个转向并不要求执行器变得“更能扛”。

相反，它强调：

- 忠实失败是合理输出
- job.failed 本身就是控制面的新输入
- 大范围恢复不应堆到执行器内部

执行器内部只保留非常局部的 micro-retry，例如：

- 瞬时网络抖动
- artifact 上传
- 外部连接建立

## 8. 适配器：LLM 与 Tool 在新模型中的位置

现有 `LLMGateway` 和 `ToolGateway` 不必消失，但应下沉为执行器内部的 capability adapters，而不是系统顶层主骨架。

### 8.1 原来的问题

原模型里它们容易被当成运行时主语。
但在新模型里：

- `RunAgentLoop` 只是某一种 attempt 类型
- LLM 调用和 Tool 调用都只是该 attempt 内部会使用的能力
- 未来也会有完全不经过 LLM / tools 的 attempt

### 8.2 新调用流程

建议流程：

1. 控制面生成一个 `agent attempt planned` 事件
2. 执行器读取该计划
3. `materializer` 根据 artifact bindings 还原 workspace
4. 执行器内部创建：
   - `LLMAdapter`
   - `ToolAdapter`
5. `RunAgentLoopExecutor` 运行本次 agent loop
   - 调 `LLMAdapter.call()`
   - 如有 tool calls，调 `ToolAdapter.execute()`
   - 记录 `llm.request/response` 与 `tool.exec/result` 事件
6. loop 结束后，执行器将 transcript、摘要、输出物化为 artifact，并写 terminal event
7. 控制面继续决策下一步

### 8.3 架构含义

因此：

- `LLMGateway` 应降级为 `LLMAdapter`
- `ToolGateway` 应降级为 `ToolAdapter`
- 顶层系统边界应变成：
  - `EventGateway`
  - `ProjectionGateway`
  - `ArtifactGateway`
  - `Effect/Attempt Executor`

## 9. 其他组件是否需要转向

## 9.1 Palimpsest 类执行器

需要转向。

方向：

- 从 runtime pipeline owner 改为 `attempt runner`
- 只执行单次 attempt
- 只产出事件和 artifacts
- 不承担任务级 orchestration

## 9.2 Trenni 类调度器 / supervisor

需要转向。

方向：

- 从“队列 + 运行容器”扩展为真正的 `event-driven control plane`
- 负责：
  - task projection
  - next-attempt decision
  - attempt leasing
  - completion / retry / validation / publication 分流

## 9.3 Pasloe 类事件系统

需要一定增强，但不应变成业务大脑。

方向：

- 继续做 append-only log
- 强化：
  - cursor / subscription
  - 因果关联
  - 幂等写入
  - task / attempt 维度查询

不应承担：

- 任务语义推理
- 调度逻辑

## 9.4 Contracts / schema 层

需要明显转向。

重点应从“共享运行时配置结构”转向：

- event envelope
- attempt contract
- artifact ref
- artifact binding
- task projection inputs
- decision contract

## 9.5 CLI / operator tooling

需要转向。

中心不再是：

- workspace
- git branch
- 临时容器日志

而是：

- 查看 task 事件时间线
- 拉取 artifact
- 从某次 attempt 重建 workspace
- 比较两个 artifact 或两个 attempt 结果

## 10. 新的可演化性体现在哪里

新的可演化性应显式分层：

- `decision policy`
  - 什么时候启动哪类 attempt
- `projection`
  - 如何从事件和 artifacts 归约 `TaskView`
- `context assembly`
  - 如何组 prompt / context
- `tooling/runtime profile`
  - 不同任务的工具集和隔离方式
- `validation/publication`
  - 改为独立 attempt 类型
- `materialization`
  - 如何从 refs 生成 workspace
- `artifact backend`
  - 本地 FS、对象存储、bundle 格式、git pack 支持都可替换

## 11. 一句话总结

这次转向的核心不是“把 git 去掉”，而是：

**把系统真相从 `workspace / process memory` 迁回 `event log + physical artifacts`，再让执行器退化成干净、短命、可替换的单次 attempt 机器。**
