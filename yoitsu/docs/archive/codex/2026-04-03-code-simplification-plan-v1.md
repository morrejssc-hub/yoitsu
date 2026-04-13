# Yoitsu Code Simplification Plan

日期：2026-04-03
范围：`yoitsu` / `yoitsu-contracts` / `trenni` / `palimpsest`
前提：不考虑兼容；不存在数据债与技术债；允许直接删除旧字段、旧路径、旧脚手架

## 1. 目标

对当前代码做一次面向最终形态的大规模精简，核心目标不是“少几行代码”，而是：

- 让系统只有一套真实契约和一条主执行路径
- 让类型和代码结构直接表达架构，而不是依赖兼容层、注释和 prompt 约定
- 删除所有已经不代表主线设计的别名、兜底分支、空壳 schema 和未启用脚手架

## 2. 精简原则

- 一个概念只保留一种表示
- 能由类型系统和函数签名表达的，不靠文档解释
- 能删除的兼容层不保留
- 能内联或折叠的中间抽象不保留
- 未接入主路径的 scaffold 不长期留在代码里
- 归档历史，不在主代码路径中纪念历史

## 3. 目标终态

### 3.1 Task / Spawn 契约

系统只接受一种规范形态：

- `goal`
- `role`
- `budget`
- `repo`
- `init_branch`
- `team`
- `eval_spec`
- `params`

其中：

- `goal/repo/init_branch/budget/team/eval_spec` 属于任务语义或任务上下文
- `params` 只允许承载 role 内部行为参数，例如 `mode=join`
- 不再允许 `prompt`
- 不再允许 `task`
- 不再允许 `repo_url`
- 不再允许 `branch`
- 不再允许 `params.repo`
- 不再允许 `params.branch`
- 不再允许 `params.init_branch`

### 3.2 事件与可观测性

- 事件只保留真实、稳定、被消费的字段
- 不保留“schema 里有，但运行时永远发空对象”的字段
- `supervisor.job.launched` 要么携带真实 resolved config 摘要，要么只保留最小启动事实，不允许半成品语义

### 3.3 执行路径

- `CLI submit -> trigger.external.received -> Trenni -> JobConfig -> Palimpsest` 只有一条 canonical path
- Planner prompt、examples、tests、runtime schema 全部使用同一套字段
- 运行时不做旧输入形态的猜测和修正

## 4. 实施顺序

## Phase 1: Contract Reset

目的：先把“允许什么输入”收紧成单一模型。

动作：

- 重写 `yoitsu-contracts` 中与 task / spawn / launch 相关的模型，只保留 canonical 字段
- 删除 `SpawnTaskData.prompt`
- 将 `repo` 与 `init_branch` 作为明确字段，而不是放在 `params`
- 对所有模型增加严格校验，拒绝 legacy key
- 清理 contracts 中与旧字段相关的测试

完成标志：

- 主 contracts 中不再出现 `prompt/task/repo_url/branch` 作为协议字段
- 所有 tests 只验证 canonical shape

## Phase 2: Runtime Path Cutover

目的：让 `palimpsest` 与 `trenni` 只消费 canonical contract。

动作：

- 重写 `palimpsest` 的 spawn task normalization，去掉对 `prompt/task/role_file/role_fn` 式 legacy 入口的兜底
- 重写 `trenni` 的 spawn expansion，只读取 canonical 字段
- 删除 `goal or prompt`、`repo or params.repo`、`branch or init_branch` 这类 fallback 分支
- 统一 root trigger 与 child spawn 的 repo context shape
- 删除 runtime 中“仅为兼容旧 payload”存在的逻辑

完成标志：

- 搜索主代码路径时，不再存在 legacy fallback 分支
- Spawn 从 prompt 生成 goal 的逻辑消失

## Phase 3: CLI / Prompt / Example Unification

目的：把所有人类入口和模型入口同步到同一种写法。

动作：

- `yoitsu submit` 只接受 canonical YAML 结构
- 删除 `task`、`repo_url`、`branch` 等输入别名
- 重写 planner / planner-join prompt 中的 Spawn 要求
- 重写 examples、smoke tasks、脚本说明
- 调整 CLI 事件展示逻辑，只展示 canonical 字段

完成标志：

- examples 与 prompt 中只出现 canonical 字段名
- CLI 输入与运行时内部契约完全一致

## Phase 4: Event Surface Pruning

目的：精简事件模型，让可观测性只保留真实信号。

动作：

- 重新审视 `SupervisorJobLaunchedData`
- 二选一：
  - 方案 A：删除 `llm/workspace/publication` 空壳字段
  - 方案 B：定义单一的 `resolved_config` 摘要对象并真实填充
- 删除不被消费的冗余字段
- 对事件消费者做同步精简，避免 ad hoc dict 解析

完成标志：

- 不存在“注释声称是 resolved config，实际 payload 是空对象”的事件
- 事件字段数量下降，但表达能力更强

## Phase 5: Delete Dead Scaffolds

目的：把尚未进入主线的占位代码清出去。

动作：

- 删除或归档未接入主流程的 scaffold 模块
- 删除与旧架构绑定的脚本、示例、注释、测试夹具
- 删除已经被文档归档的 ADR 编号残留注释，避免代码继续围绕历史编号组织
- 合并重复脚本和重复入口，保留一条 operator 路径

原则：

- 如果一个模块当前不是主链路的一部分，也没有立即落地计划，就不继续留在主目录里假装“即将实现”

完成标志：

- 主仓库只保留当前运行主线需要的模块
- 归档材料与主代码路径完全分离

## Phase 6: Structural Collapse

目的：在契约统一后，再处理较大的结构折叠。

动作：

- 精简 `Trenni supervisor` 内部状态推进与执行启动边界
- 明确 intake path 与 execution path 的唯一接口
- 合并重复的数据搬运对象，减少 `TaskRecord / SpawnedJob / SpawnDefaults / launch event / JobConfig` 间的重复字段映射
- 把“任务语义 -> 运行时配置”的转换收敛成一个清晰的 builder 边界

完成标志：

- 核心执行链路中的中间对象更少
- 字段搬运和重复赋值显著减少

## 5. 删除清单

下面这些概念应默认进入删除名单：

- `prompt` 作为 task/spawn 协议字段
- `task` 作为 goal 的别名
- `repo_url` 作为 repo 的别名
- `branch` 作为 `init_branch` 的别名
- `params.repo`
- `params.branch`
- `params.init_branch`
- 空壳 `llm/workspace/publication` 事件字段
- 仅为兼容旧 schema 存在的 fallback 分支
- 未接入主链路的 scaffold
- 继续引用已归档 ADR 的历史性注释

## 6. 验收标准

满足以下条件才算精简完成：

- 搜索主代码目录，不再出现 legacy key 的协议级用法
- 搜索主代码目录，不再出现针对旧输入形态的 fallback 逻辑
- prompt、examples、CLI、contracts、runtime 使用同一套字段命名
- `supervisor.job.launched` 等关键事件不再包含空壳语义
- 主链路模块数量更少，数据搬运层级更浅
- 文档只解释原则和边界，不再解释代码已经能直接表达的细节

## 7. 执行建议

这次精简应按“删契约 -> 删入口 -> 删事件 -> 删脚手架 -> 再折叠结构”的顺序推进，不要一开始就做跨仓大重写。

推荐拆成三个连续 PR 批次：

1. Contract + runtime cutover
2. CLI/prompt/example + event pruning
3. Scaffold deletion + structural collapse

## 8. 第一张工单

建议直接从下面这张工单开始：

`spawn-contract-cutover-without-compatibility`

范围：

- contracts
- palimpsest spawn normalization
- trenni spawn handler
- yoitsu submit
- planner prompts
- examples/tests

原因：

- 这是当前最集中的复杂度来源
- 它一旦收紧，后续事件、脚手架、结构折叠都会更容易做
- 这一步最符合“代码自己表达架构”的目标
