# 执行表面与控制面 Capability 讨论纪要

日期：2026-04-14
状态：讨论纪要，非正式 ADR
来源：围绕 ADR-0019、smoke 测试失败与 capability 边界的一轮设计讨论

## 1. 背景

近期为了处理 smoke 测试中的 bundle / role / workspace 语义错配，引入了 `output_authority` 字段，并在 runner 中据此选择工作目录。

讨论过程中逐步确认，这个字段的 ADR 表述与系统既有原则之间存在明显张力：

1. 系统已经明确 `event store` 是唯一真实来源。
2. `event` 不对外部连接、发布结果或运行时生效作静态担保；这些都必须由实际事件证明。
3. `output_authority` 的 ADR 文案容易被理解为“为 role 引入第二套真实性来源”。
4. 但当前代码里，这个字段的实际作用远小于 ADR 文案宣称的范围。

因此，本纪要的目标不是为 ADR-0019 辩护，而是把当前讨论中已经澄清的事实、问题和可能的替代方向记录下来。

## 2. 已确认的事实

### 2.1 Event store 仍然是唯一真实来源

这一点没有改变，也不应改变。

以下问题都只能由事件证明，而不能由 role 元数据、summary 或投影视图静态推出：

1. agent 是否真的调用了工具
2. capability 是否真的完成了 finalize / publication
3. 外部连接是否有效
4. 外部运行时是否真的生效
5. supervisor 是否接受了这次 job 生命周期

因此，任何新字段都不应被解释为“新的 truth source”。

### 2.2 `output_authority` 当前实现的真实作用很窄

截至当前实现，`output_authority` 主要只影响 runner 如何为 role 选择执行目录：

1. `repository` -> `target_workspace`
2. `live_runtime` -> `bundle_workspace`
3. `analysis` -> 临时目录

也就是说，它当前更接近：

1. 执行表面声明
2. 默认工作区路由
3. job 的 `cwd` 选择规则

而不是：

1. job 真值来源
2. evaluator 的终态判据
3. 外部系统是否成功的证明

### 2.3 目前的挂载与启动责任在 Trenni，不在 capability

当前实际启动链路如下：

1. Pasloe 是长驻 event store service。
2. Trenni 是长驻 supervisor / control plane service。
3. 每个 job 由 Trenni 启动一个短生命周期的 `palimpsest` 容器。
4. Trenni 在 job 启动前准备 bundle workspace 和 target workspace。
5. Trenni 再把这些目录 bind mount 到 job 容器中。
6. Palimpsest 容器启动后才进入 role resolution、context、agent loop、capability setup/finalize。

因此，当前“挂载 topology 决策”天然发生在 Trenni 侧，而不是 capability 侧。

### 2.4 当前 capability 的职责主要分成两类

当前代码中的 capability 主要有三种代表：

1. `git_workspace`
   - `setup()` 基本是 no-op
   - 真正的 target repo clone 由 Trenni 先完成
   - `finalize()` 负责 `git add/commit/push`

2. `cleanup`
   - 清理 target workspace 或资源句柄
   - 不承担权威语义

3. `factorio_runtime`
   - 同步 bundle 脚本到 live mod 目录
   - 建立 RCON 连接
   - 执行 `reload_script`
   - finalize 时关闭 RCON

这表明一个重要事实：

当前 capability 已经部分承担“影响非隔离环境”的职责，但其生命周期仍被放在 job 容器内部。

## 3. 对 ADR-0019 的核心质疑

### 3.1 问题不在代码实现，而在概念表述越界

当前 `output_authority` 在代码中的影响范围还比较有限，只是工作区路由。

真正有问题的是 ADR-0019 的表述方式。它把这个字段描述成：

1. role 的唯一输出权威
2. 哪个系统对 role 的产物负责
3. repository / live runtime / analysis 的语义归属

这种表述很容易被理解为：

1. 除 event store 之外，repository 或 live runtime 也成了新的真值来源
2. evaluator 或 smoke 可以依据这个字段重新解释成功含义
3. “真实发生了什么”可以通过 role 元数据先验推出

这与“event store 是唯一真实”原则冲突。

### 3.2 它想解决的真实问题更像是“执行表面”，不是“输出权威”

这轮讨论中逐步确认，`output_authority` 想解决的实际问题更接近：

1. 这个 role 默认应在什么目录下执行
2. 这个 role 默认允许对哪块目录产生写入
3. runner 应把哪块 workspace 当作它的工作面

如果是这样，那么 `output_authority` 这个命名和 ADR 文案都过重了。

更准确的名称可能是：

1. `execution_surface`
2. `workspace_mode`
3. `write_surface`

无论最终名字是什么，语义都应严格限制在“执行表面/工作区路由”，而不是“真实性归属”。

## 4. 当前讨论中形成的更强判断

### 4.1 系统本质上有两类阶段

这轮讨论里提出了一个更接近实际的分层：

1. `agent loop` 阶段
   - 模型驱动
   - 开放式
   - 不可信
   - 必须在隔离环境中运行

2. 其他固定生命周期阶段
   - 代码固定
   - 可审查
   - 行为稳定
   - 原则上可以在非隔离环境中运行

如果接受这个分层，那么 capability 的本质就不再只是“job 容器内的 setup/finalize hook”，而更像：

“除 agent loop 之外的受控系统操作单元”

### 4.2 这比 `output_authority` 更贴近问题本体

因为当前真正需要回答的问题不是：

“哪一个系统是 role 的真实性来源？”

而更像是：

1. 哪些准备动作必须在 agent loop 之前完成
2. 哪些动作可以在非隔离环境中安全执行
3. 哪些资源应该由 control plane 准备并挂载
4. 哪些副作用必须留在 job 容器内

这说明设计中心更应该落在：

1. 生命周期分层
2. 控制面与执行面的边界
3. capability 的运行位置

而不是 role 的“输出权威”分类。

## 5. 对新方向的初步收敛

### 5.1 可以接受的高层判断

目前讨论中相对稳定的判断是：

1. Palimpsest 总应拥有一个可执行工作区。
2. bundle 应作为能力基础和任务定义基础被挂载进来。
3. 是否存在 target workspace，以及它如何准备，原则上由 control plane 决定。
4. agent loop 明确属于隔离执行面。
5. agent loop 之外的固定生命周期逻辑，可以考虑由非隔离环境承接。

### 5.2 如果沿这个方向前进，capability 需要拆层

如果 capability 未来要承担更多非隔离环境准备职责，那么不应继续维持“单一 capability 接口”。

更合理的做法是显式拆成两层：

1. control-plane capabilities
   - 在 Trenni 侧执行
   - 负责 host 资源准备、挂载解析、外部连接 preflight、runtime attach/detach

2. job-side capabilities
   - 在 Palimpsest 容器内执行
   - 负责 job 内 finalize、局部同步、资源收尾

否则会出现以下问题：

1. 同一个 `setup()` 到底在哪个进程、哪个权限边界里执行会变得模糊
2. capability 接口会同时承担 launch topology 和 in-job lifecycle 两种责任
3. 调试时很难判断某个失败发生在 control plane 还是 job 容器里

### 5.3 不能把 bundle 任意代码直接提升到 Trenni 执行

这是讨论中另一个重要约束。

即便 capability 要在非隔离环境里跑，也不意味着：

“Trenni 可以直接 import 并执行 bundle 提供的任意 Python 代码”

原因：

1. Trenni 是长驻 control plane，权限边界高于短命 job 容器。
2. bundle 代码本质上仍属于任务扩展面，不应默认获得 supervisor 级执行权。
3. 这会把 bundle 扩展能力和 control plane 信任边界混在一起。

因此，如果引入 control-plane capability，更安全的前提是：

1. 先只允许 built-in / allowlisted capability
2. bundle 只能声明需求，不能任意注入 control plane 代码
3. 所有控制面动作必须落事件

## 6. 对 smoke 问题的反向结论

这轮讨论中的一个重要共识是：

不能因为 smoke 测试通不过，就去修改 truth model。

更具体地说：

1. smoke 暴露的是 bundle / role / workspace / capability 边界不清
2. 它不构成“为系统引入第二套真实性来源”的理由
3. 如果只是想解决工作区路由问题，应在执行表面或启动拓扑层面解决
4. 不应把这种问题包装成“输出权威”的语义升级

## 7. 当前最可行的短期结论

在没有完成更大重构前，短期内最稳妥的解释应当是：

1. 保留 event store 作为唯一真实来源。
2. 不把 `output_authority` 解释为 truth source。
3. 把它降级理解为“执行表面/工作区路由字段”。
4. evaluator 和 supervisor 的终态解释仍只依赖事件证据。
5. capability 是否迁移到 control plane，需要单独设计，不应隐式塞进现有 ADR-0019。

## 8. 未决问题

以下问题尚未定案，需要后续单独设计：

1. `output_authority` 是否应被删除、重命名，还是仅重写 ADR 文案
2. 工作区选择是否应该完全转为 launch-time metadata，而不是 role metadata
3. 是否需要正式引入 `control-plane capability` 与 `job-side capability` 两层模型
4. bundle 对 control-plane 的需求应该用静态声明表达，还是用受限 hook 表达
5. `factorio_runtime` 这类 capability 中，哪些步骤应迁移到 Trenni，哪些应保留在 job 容器

## 9. 一句话总结

本次讨论的收敛结论不是“role 需要输出权威”，而是：

系统真正缺少的是对“执行表面”和“控制面 capability”的清晰建模，而不是对 truth model 的再次扩展。
