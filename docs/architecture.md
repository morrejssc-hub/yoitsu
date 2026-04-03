# Yoitsu 架构指南

Yoitsu 是一个围绕“事件流”与“产物存储”（Artifacts）构建的自我演进 Agent 架构。
当前所有的设计决策收敛于一个核心思想：**系统的唯一真实数据源仅为 `Event Store` 与 `Artifact Store`，任何运行时内存、工作区缓存均属于无需持久化的临时物化视图。**

所有的具体接口、数据模型流转与文件层职责均已在相关代码的 Docstrings 中详细声明，请直接参阅代码。本指南仅提供最高维度的认知模型。

## 核心设计理念：双真实数据源 (Dual Source of Truth)

1. **Pasloe (Event Store)**：系统的时序大脑。采用只追加模式（Append-Only）记录所有生命周期事件、观察行为、工具调用以及大模型的判断。它回答“发生了什么”。
2. **Artifact Store (产出内容寻址)**：系统的物质沉淀。使用基于内容寻址的对象存储，承载一切 Blob 与目录树快照（Tree）。它回答“产生了什么对象”。注意：Git 等其他外围机制被视为向下兼容的数据接收者（Compatibility Receipt），而不是规范源。

> [!IMPORTANT]
> 任何任务逻辑的中间状态如果不记录到上述两者之一，便不应该对下一步决策产生影响。执行器内部不存在长活（Long-Lived）状态上下文。

## 系统四大组件

- **Trenni 控制面 (Control Plane)**：绝对确定性的事件驱动调度引擎。它通过将 Pasloe 中的事件池以及 Artifact 元数据进行归约，计算得出下一步需要执行什么是 `Attempt` 还是终止任务，绝不干涉任务的业务语境解释。
- **Palimpsest 执行器 (Attempt Runner)**：一次性（Single-Attempt）、短寿命的无状态执行容器。负责接收确定的 Attempt 契约（输入包含 Artifact 引用），物化本地工作区（Workspace）执行代码逻辑、发配大模型请求，并最终将产出固化回事件与 Artifacts，随后彻底抛弃本地实例。
- **Pasloe 存储底座**：事件总线系统。在任务语义层提供盲派发。
- **yoitsu-contracts**：隔离并收拢上述三个执行实体与边界的共有数据契约、协议与事件基础原型定义。

## 编排与信息边界

**Spawn 是唯一的编排原语。** 系统没有预定义的 DAG 或工作流引擎。Agent 调用 `spawn(tasks=[...])` → Trenni 展开为子 Task + Job + 可选 Join Job。任务分解决策属于 Planner 角色（LLM 判断），不属于 Trenni。

**系统中的每个字段严格归属于三类之一：**
1. **任务语义** (goal, repo, budget, eval_spec, team) — 由 Trigger 或 Spawn Payload 携带，存于 TaskRecord
2. **执行配置** (model, tools, publication strategy) — 由 `evo/` 中的 Role 定义派生，Spawn Payload 不可设置
3. **运行时身份** (job_id, evo_sha, container_name) — 由 Trenni 在 Job 创建时机械分配

**双层裁定 (Two-Layer Verdict)：** 每个终结 Task 同时携带确定性的结构裁定（跑了什么、结果如何）和可选的语义裁定（目标是否达成），详见 ADR-0002。

## 组件间协作模式

- **Pasloe 两阶段流水线**：事件写入先获得 `accepted`（持久性边界），随后异步进入 `committed`（消费者可见）。生产者仅依赖 accepted；Trenni 仅消费 committed。这个分离保证宕机恢复时不会丢失已确认但未投影的事件。
- **Trenni 摄取/执行分相**：Supervisor 循环分为摄取阶段（确定性事件路由与状态变更）和执行阶段（容器启动等副作用）。摄取失败回滚 cursor；执行失败不回滚。这使得重放和检查点语义简洁可靠。
- **Trenni → Palimpsest 单向推送**：Trenni 将 `JobConfig` 序列化为 base64 注入容器环境变量。Palimpsest 通过 Pasloe 发出事件回传。两者之间没有直接通信通道。

## 可演化隔离区 (Evo Layer)

所有的逻辑分支迭代和 Agent 聪明程度的提升都在代码根目录的 `evo/` 中进行。这是唯一个允许 Agent 主动修改从而完成自我迭代的代码区域。
Trenni 采用强力的隔离设计，将 `team` 视为一等隔离边界（例如：不同的容器镜像、环境变量与权限约束，并通过物理路径定位 `evo/teams/<team>/...` 层叠执行策略）。这种设计天然适配因子化任务隔离与未来自治扩展。

## 自优化闭环

系统通过正常的任务管道实现自我改进——没有特殊的优化模式。结构化观察信号（`observation.*`）在执行过程中机械发出，累积到阈值后自动触发 Review Task，产出改进提案，提案成为修改 `evo/` 的普通优化 Task。预算预测精度（而非绝对成本）作为系统健康度的代理指标。详见 ADR-0010。
