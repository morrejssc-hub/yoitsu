# 合并后的架构设计

日期：2026-04-02
状态：基于当前代码与近期讨论的整合稿
目的：替代现有分散、重复、彼此漂移的系统级文档

## 1. 这份文档解决什么问题

当前 `docs/` 中同时存在：

- 早期系统级 ADR
- 实现计划
- review 记录
- 重构设想
- 新的 artifact store 转向说明

这些文档里有不少内容已经互相覆盖、互相修订，甚至与代码现状不再完全一致。

这份文档不试图保留所有历史推演，而是给出一份新的、压缩后的系统设计主线，满足两个要求：

1. 以当前代码结构为锚点。
2. 吸收最近讨论得到的新结论，尤其是：
   - Palimpsest 继续保留四阶段
   - artifact store 成为新的物理真实源之一
   - git 从系统内部真实源降级为外部兼容技术

## 2. 系统总览

Yoitsu 现在应被理解为四个核心部分：

- `Pasloe`
  - append-only event store
  - 提供 accepted/committed 两阶段语义
  - 保存“发生了什么”
- `Artifact Store`
  - 内容寻址的物理对象存储
  - 保存“产出了什么”
- `Trenni`
  - 调度、任务状态、运行时配置组装、隔离控制
  - 不执行 agent 逻辑
- `Palimpsest`
  - 单 job 执行器
  - 负责四阶段运行时、LLM/tool loop、事件发射

`yoitsu-contracts` 提供共享 schema 和类型约束，`yoitsu` CLI 提供 operator 入口。

## 3. 两类真实源

新的主结论是：系统真实源不再是 “git + event stream”，而是：

1. `Pasloe event stream`
2. `Artifact store`

这两者各自负责不同事实：

- `events`
  - 谁触发了任务
  - 哪个 job 被排队、启动、完成、失败
  - 哪个 artifact 被引用、消费、产生
  - 任务结构和生命周期如何推进

- `artifacts`
  - 某次执行的物理输入是什么
  - 某次执行的物理输出是什么
  - 哪些目录树、文件、checkpoint、报告可以被后续 job 重新物化

以下内容都不再是权威状态：

- workspace 目录
- 进程内返回值
- git 分支本身
- runtime memory

git 仍然保留价值，但它属于：

- 外部协作协议
- 兼容回执
- 生态集成手段

而不是系统内部唯一输出通道。

## 4. Job、Task、Attempt

当前代码已经稳定地把 `job` 和 `task` 区分开：

- `job`
  - 一次 Palimpsest 执行
  - 单次、短命、可忠实失败
- `task`
  - 逻辑工作单元
  - 生命周期由 Trenni 管理

在新的文档主线里，建议再补一个更清晰的概念：

- `attempt`
  - `job` 的运行语义名称
  - 用来强调“这是一次性执行尝试，而不是长活 actor”

是否在代码中正式引入 `attempt` 类型，可以后续再定；但在文档上，应该开始用它解释 Palimpsest 的角色。

## 5. Palimpsest：保留四阶段，但改变解释

Palimpsest 仍然保持四阶段，这和当前代码一致：

1. `preparation`
2. `context`
3. `interaction`
4. `publication`

但四阶段的解释要更新。

### 5.1 Preparation

职责：

- 建立本次 job 的私有工作区
- 做 copy-in / materialization
- clone / 解包 / staging / 环境准备
- 建立短生命周期资源句柄

新的关键点：

- preparation 处理的是 artifact 或外部源的输入物化
- 它不再被理解为“git checkout 阶段”
- workspace 只是私有副本，不是权威源

### 5.2 Context

职责：

- 从 job config、workspace、Pasloe、artifact metadata 中组装 agent 可见上下文
- 加载 prompt、上下文片段、join/eval 信息

新的关键点：

- context 仍然是第一个主要 evolvable 点
- 它可以查询 Pasloe，也可以读取本地已物化内容
- 它不拥有长期状态，只负责当前 attempt 的上下文构造

### 5.3 Interaction

职责：

- 跑 LLM 与工具调用循环
- 发出 `agent.llm.*`、`agent.tool.*`、`agent.job.*` 事件

新的关键点：

- interaction 不负责系统级决策
- 它只负责当前 attempt 的执行
- tool/LLM gateway 继续保留，但只是 runtime 内部适配层

### 5.4 Publication

职责：

- 将本次 job 的输出保存为 artifact
- 可选地产生 git 回执
- 生成 completion event 所需的输出引用

新的关键点：

- publication 的规范输出是 artifact bindings
- `git_ref` 是兼容字段，不再是唯一真实输出

## 6. Trenni：仍是调度与控制面，不引入“可演化决策内核”

近期讨论否掉了一个过度设计方向：不要把 Trenni 变成可演化 policy engine。

因此新的解释应保持克制：

- Trenni 仍然是 deterministic control plane
- 不做 evolvable task policy
- 不做 attempt 内阶段跳转选择
- 不把 planner 的语义决策搬到控制面

Trenni 负责：

- 任务状态推进
- spawn expansion
- eval / join 编排
- 条件与并发控制
- 运行时规格构建
- 容器隔离与 replay/checkpoint
- artifact store 访问配置

它读事件、排 job、启动容器，但不替代 agent 本身思考。

## 7. Pasloe：继续做 append-only event store，不升格为业务大脑

Pasloe 当前代码和文档已经比较稳定：

- `accepted` 写入
- `committed` 可见
- webhook / cursor 查询
- domain read models

在新的主线里，Pasloe 继续只做：

- 事件持久化
- 事件可见性
- 查询与分发

不要把任务语义解释再塞回 Pasloe。

## 8. Artifact Store：唯一新增的一等基础设施

Artifact store 是这轮讨论中唯一保留下来的重大结构性新增。

它的定位是：

- 内容寻址
- 物理对象存储
- 支持至少 `blob` 与 `tree`
- 通过 `ArtifactRef` 和 `ArtifactBinding` 进入事件与运行时

它不做：

- 高层语义判定
- 任务域判断
- 运行时 policy

文档上应把 artifact store 看成和 Pasloe 平级的真实源，而不是 git 的附属缓存。

## 9. 共享 contracts 的角色变化

`yoitsu-contracts` 不再只是“JobConfig + events”的容器。

在新的主线里，它应承载三类稳定对象：

1. 事件模型
2. 运行时配置模型
3. artifact 相关模型

换句话说，contracts 现在是：

- `Pasloe <-> Trenni <-> Palimpsest` 的共享边界
- 未来文档整理时，应该把它单独提升成一个明确章节，而不是只在 ADR 中零散提及

## 10. 文档中的可演化性应如何表达

这里需要纠正一个常见误区：

“可演化”不等于“必须是 `fn + decorator`”。

当前代码里的主要 evolvable 面有：

- roles
- prompts
- context providers
- evo-defined tools

但随着 artifact 引入，文档应开始区分三类 evolvable 对象：

1. 行为型对象
   - 适合代码实现
   - 如 role、context provider、tool、publisher

2. 声明型对象
   - 适合配置表达
   - 如 runtime profile、tool allowlist、artifact store config

3. 组合型对象
   - 用于把多种能力拼成一个 job/role/runtime recipe

也就是说，新的系统文档不应该再把一切 evolvable 点都表述成“Python 函数”。

## 11. 新的总文档顺序

建议新的阅读顺序不是按历史 ADR 编号，而是按代码与运行边界：

1. 合并后的架构设计
   - 也就是本文
2. 共享 contracts 与事件模型
3. Pasloe：事件存储与可见性
4. Trenni：任务控制面与隔离
5. Palimpsest：四阶段 runtime
6. Artifact Store：物理对象层
7. 外部任务域扩展（如 Factorio）
8. 预算、治理、优化类机制

这个顺序比现有 ADR 的历史顺序更符合当前系统理解成本。

## 12. 当前文档中最值得保留的部分

按代码现实和讨论结果，以下几类文档仍有高价值：

- `ADR-0001`
  - 但应收缩为系统分层与术语基线
- `ADR-0002`
  - 任务/作业生命周期仍然重要
- `ADR-0004`
  - 预算系统独立存在
- `ADR-0010`
  - 治理与自优化仍然是独立主题
- `ADR-0013`
  - artifact store 是新的新增基础设施

而以下内容应倾向于被合并或重写：

- `ADR-0003` 与 `ADR-0009`
  - 共同解释 runtime，但已明显漂移
- `ADR-0007`、`0008`
  - 与 task/job boundary、spawn ingestion 强相关，适合合并
- `ADR-0011`、`0012`
  - 外部任务源 / team / factorio，适合在新的 runtime 解释下重写

## 13. 结论

新的主线应当是：

- Yoitsu 是一个以 `Pasloe events + artifact store` 为双真实源的系统
- Trenni 是 deterministic control plane
- Palimpsest 是四阶段的单次 attempt runtime
- git 不再是系统内部唯一真实输出，只是外部兼容技术
- artifact store 是当前唯一值得正式引入的新基础设施
- 文档应从“历史推演记录”转向“按代码边界组织的合并设计”

这份文档应作为新的系统级总入口，替代当前 `docs/architecture.md` 和多份分散系统级 ADR 的共同职责。
