# Yoitsu System Plan

日期：2026-04-03
状态：基础能力已经打通，进入系统级闭环阶段
范围：`yoitsu` / `yoitsu-contracts` / `trenni` / `palimpsest` / `pasloe`

## 1. 当前基线

已完成能力：

- canonical contract、runtime hardening、observation loop、external trigger、artifact runtime 均已落地
- 非 Git 任务已具备 artifact 输入/输出主链路
- GitHub 上下文、reviewer、PR 工具、外部触发入口已具备基本能力

当前不再以“补基础设施”为主，而是转向“让这些能力稳定协同工作并形成自治闭环”。

## 2. 下一阶段目标

下一阶段只做四件事：

1. `Autonomous Review Loop`
2. `Execution Safety Boundary`
3. `Stateful Domain Validation`
4. `Operator Surface Consolidation`

## 3. 执行顺序

1. 先做 `Autonomous Review Loop`
2. 再做 `Execution Safety Boundary`
3. 再做 `Stateful Domain Validation`
4. 最后做 `Operator Surface Consolidation`

原因：

- 当前已经有 observation、reviewer、external trigger，最应该先把“自动 review -> 优化任务”真正闭环
- 运行时安全边界会影响后续所有自治任务
- 有了 artifact runtime 后，最值得验证的是强状态任务域
- operator surface 最后收敛，避免在功能继续变化时重复返工

## 4. Phase 1: Autonomous Review Loop

当前状态：

- `observation_threshold` 事件已能触发 `optimizer`
- `optimizer` 角色、prompt、`ReviewProposal` schema、proposal->trigger 转换都已存在
- 当前剩余缺口是：`optimizer` 的实际输出还没有在运行时主链中被消费

当前阶段只做最后一段闭环：

- 在主链中解析 `optimizer` 输出为 `ReviewProposal`
- 将 `ReviewProposal` 自动转成普通 optimization trigger/task
- 补 `observation_threshold -> optimizer -> proposal -> optimization task` 端到端 smoke

完成标志：

- `optimizer` 不再只是“能被触发”，而是能自动产出下一张优化任务
- `ReviewProposal.from_json_str()` 和 `review_proposal_to_trigger()` 不再只停留在模型/测试层

建议工单：

`autonomous-review-loop-output-closure`

## 5. Phase 2: Execution Safety Boundary

目标：把当前可运行的 agent/tool/runtime 路径收紧到安全可控边界内。

动作：

- 为 `evo/` 内纯 Python 工具增加子进程隔离
- 统一 tool 级 timeout / memory / output 限制
- 明确 artifact materialize / publication 对工作区关键路径的保护规则
  - 禁止覆盖 `.git`
  - 禁止危险路径逃逸
  - 明确 overlay 顺序
- 为 runtime failure / publication failure / artifact failure 增加回归测试

完成标志：

- 纯 Python tool 不再直接无边界运行在主进程内
- artifact 输入不会破坏 repo workspace 或逃逸到工作区外

建议工单：

`execution-safety-boundary`

## 6. Phase 3: Stateful Domain Validation

目标：用一个强状态任务域验证当前架构不是只适合 Git 型任务。

动作：

- 选定一个状态型任务域作为正式验证对象：
  - `factorio`
  - 或等价的长状态外部系统
- 验证 team 隔离、artifact checkpoint、序列化执行、runtime context 资源接入
- 用至少一条端到端 smoke 验证：
  - 输入 checkpoint
  - 单任务执行
  - 输出 checkpoint / report artifacts

完成标志：

- 系统被证明能处理“非 Git + 强状态 + 串行隔离”任务
- `Artifact Store` 不只是 non-Git helper，而是状态任务主载体

建议工单：

`stateful-domain-validation`

## 7. Phase 4: Operator Surface Consolidation

目标：让 operator 能直接看到任务图、observation 聚合、artifact 输出和 review proposal。

动作：

- 在 CLI / TUI / control API 中统一暴露：
  - task lineage
  - observation aggregate
  - artifact bindings
  - review proposals
- 清理当前仍然偏底层的 operator 输出
- 补齐 smoke 和回归测试，保证排障入口稳定

完成标志：

- operator 不需要手工拼事件细节就能看清任务、产物和 review 状态
- 当前系统的“发生了什么 / 产出了什么 / 下一步建议什么”都可直接观察

建议工单：

`operator-surface-consolidation`

## 8. 约束

- 不回退到兼容层
- 不引入第二套协议或第二套 runtime 路径
- 计划优先体现为代码、测试、smoke，不体现为解释性文档堆积

## 9. 验收方式

每个 phase 完成时都必须满足：

- 主路径代码闭环
- 受影响测试通过
- 至少一条端到端 smoke 通过
- 行为可以直接由代码和测试表达，而不是靠额外说明维持
