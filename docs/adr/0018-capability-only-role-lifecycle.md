# 0018: Capability-Only Role Lifecycle

- Status: Proposed
- Related: ADR-0015, ADR-0016

## 1. 现状与存在的问题

ADR-0016 已经确立 capability 是 runtime 生命周期管理的标准模型，但系统当前仍保留一条完整的 legacy 路径：当 role 没有声明 capability 需求时，runtime 仍回退到 role 级别的 preparation / publication 语义。这带来四个结构性问题：

1. **Role contract 不唯一**：bundle 作者无法只看 role 声明就理解执行语义。相同的 role 表面上都叫 role，实际上有两套运行模型。
2. **Runtime 继续解释 bundle 内部历史遗留语义**：`workspace_override`、`publication_strategy`、`branch_prefix` 之类的概念仍由 runtime 识别和分支处理，导致 runtime 继续承担本应被 capability 吸收的语义。
3. **`needs=[]` 的含义被污染**：它既可能表示“这个 role 不需要额外生命周期服务”，也可能表示“走旧系统”。一个空列表不应承载两种完全不同的执行模型。
4. **迁移永远无法真正结束**：只要 fallback 仍然是正式路径，bundle 作者就会继续沿用旧语义，runtime 也必须继续维护两套推理和测试心智。

## 2. 做出的决策与原因

### 2a. Capability 生命周期成为唯一执行模型

Role 的执行生命周期统一为：

1. runtime 建立 job 上下文
2. 按 role 声明的 capability 需求执行 setup
3. 组装 context 并运行 agent loop
4. 按相同 capability 集执行 finalize
5. runtime 根据 capability 返回结果与运行时监督结果确定终态

不再存在“role 没有 capability 时改走另一套 preparation/publication 流程”的制度性分支。

**原因**：ADR-0016 的价值在于把 lifecycle 从 role 自定义函数里抽离出来。如果 runtime 继续保留完整 fallback，该抽离实际上并未完成。

### 2b. 空 capability 集不再表示 legacy fallback

`needs=[]` 的含义固定为：“该 role 不需要额外的 setup/finalize 服务。”它不再触发任何旧式执行路径。

analysis-only role、planner、纯 evaluator 等都可以是空 capability 集，但它们仍处在统一的 runtime 生命周期之内。

**原因**：空集合应表示“无需求”，而不是“切换模型”。

### 2c. Role contract 收敛到声明式职责

Role 的公开 contract 只保留三类声明：

1. 角色元数据与语义身份
2. `needs`
3. `contexts` 与 `tools`

role 不再通过独立的 preparation/publication 钩子向 runtime 注入另一套生命周期协议。

**原因**：role 应描述“我是什么、我需要什么、我能用什么”，而不应重新定义 runtime 执行框架。

### 2d. 下列 legacy 概念退出 role/runtime contract

以下概念不再作为 role 与 runtime 之间的制度性接口继续存在：

- role 级别的 `preparation_fn`
- role 级别的 `publication_fn`
- `publication_strategy`
- `branch_prefix`
- `workspace_override`

它们对应的语义要么进入 capability，要么被更高层的任务/调度/交付决策吸收。

**原因**：这些概念正是双轨制残留的载体。只保留名字而试图“约束使用方式”，最终仍会把 runtime 拉回旧模型。

### 2e. 顺序依赖属于单个 capability 内部事务

如果若干生命周期动作之间存在强顺序依赖，它们必须归属于同一个 capability，而不是依赖 runtime 在 capability 之间建立隐式排序语义。

**原因**：ADR-0016 已经拍板 capability 之间不承载复杂顺序协议。彻底迁移时必须坚持这一点，否则只是把 legacy 耦合换个位置继续存在。

### 2f. Role 终态不再由 role 私有 publication 语义定义

Job 是否真正完成，不再由 role 自带的“skip publication”之类声明来解释。终态由统一 runtime 生命周期中的 capability 结果与运行时监督结果共同决定。

**原因**：只要 role 仍能通过私有 publication 语义改变终态解释，role 就仍在定义执行模型而不是声明能力。

## 3. 期望达到的结果

- runtime 只有一套生命周期推理模型
- role 作者面对的是单一 contract，而不是“新模型 + 旧模型”并存
- capability 成为所有 setup/finalize 责任的唯一归宿
- 空 capability 集可以自然表达 analysis-only role，而不再意味着“历史遗留模式”
- 彻底迁移具备明确完成条件，而不是长期兼容

## 4. 容易混淆的概念

- **没有 capability** 不等于 **没有 lifecycle**
  - 前者表示该 role 没有额外 runtime 服务需求
  - 后者是错误理解；所有 role 仍在统一生命周期内执行

- **Role 声明** 不等于 **Runtime 框架**
  - role 负责声明依赖与语义
  - runtime 负责执行统一生命周期

- **Capability** 不等于 **Tool**
  - capability 管理 job 前后存在的基础设施与持久化责任
  - tool 是 agent loop 中按需调用的动作接口

## 5. 对之前 ADR 或文档的修正说明

- ADR-0016 中关于“为逐步迁移而保留 fallback”的表述应被视为过渡性安排，而不是长期架构承诺。
- ADR-0015 中“workspace 永远是 ephemeral”这一决定继续有效，并在本 ADR 中获得更强约束：role 不再能通过独立接口要求 runtime 切回旧式 workspace 语义。
- `docs/architecture.md` 中关于 capability 与 legacy path 并存的描述应在后续文档修订中降格为历史说明，而不再描述目标架构。
