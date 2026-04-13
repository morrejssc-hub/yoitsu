# Autonomous Review Loop Output Closure

日期：2026-04-04
状态：已完成 ✅
范围：`yoitsu-contracts` / `trenni` / `palimpsest`

## 目标

补上 `Autonomous Review Loop` 的最后一段闭环：

- observation threshold 已能触发 `optimizer`
- `optimizer` 已有独立 prompt / role / output schema
- `ReviewProposal` 已能转换为下一张 optimization trigger

当前缺口是：

- 系统还没有在运行时主链里消费 `optimizer` 的实际输出
- `ReviewProposal.from_json_str()` 和 `review_proposal_to_trigger()` 仍停留在模型/测试层

这张执行卡只做“optimizer 输出接单”，不重复做 observation、trigger、role、schema 基础设施。

## 范围

### In Scope

- 定义如何识别 optimizer job 的最终输出
- 在主链路中解析 optimizer 输出为 `ReviewProposal`
- 将 `ReviewProposal` 转成普通 trigger/task
- 为这条闭环补端到端 smoke

### Out of Scope

- 重新设计 observation schema
- 重新设计 optimizer prompt
- 扩展 GitHub review 路径
- operator UI/TUI 展示

## 实施步骤

### Step 1: Define Runtime Handoff

目标：明确 optimizer 输出在哪个 runtime 边界被消费。

动作：

- 选择唯一消费点：
  - 优先在 `agent.job.completed` / task termination 之后消费
  - 不要在多个阶段重复解析
- 明确只有 `optimizer` role 走这条 proposal 解析路径
- 明确解析失败时的行为：
  - 不生成后续任务
  - 发出可观察错误/summary

完成标志：

- `ReviewProposal` 的消费边界唯一且可测试

### Step 2: Parse Optimizer Output

目标：把 optimizer 的最终文本输出转成结构化 proposal。

动作：

- 从 optimizer job 完成事件中提取最终文本
- 调用 `ReviewProposal.from_json_str(...)`
- 对成功/失败两种情况分别建立测试
- 保证不会误解析 reviewer / implementer 等其他角色输出

完成标志：

- optimizer job 输出可稳定解析为 `ReviewProposal`

### Step 3: Convert Proposal To Next Task

目标：把解析出的 proposal 自动转成普通优化任务。

动作：

- 调用 `review_proposal_to_trigger(...)`
- 将 trigger 送入现有 trigger/task 主链，而不是旁路
- 保持 canonical contract，不新增特殊 task path
- 保证 proposal 中的 task template 字段能正确落入 TriggerData / SpawnedJob

完成标志：

- proposal 不再停留在数据模型层，而是能生成实际后续任务

### Step 4: End-to-End Smoke

目标：验证完整自治 review 闭环。

最小 smoke：

1. observation threshold event
2. `optimizer` task created
3. optimizer produces valid proposal JSON
4. runtime parses proposal
5. proposal converted to ordinary trigger
6. optimization task created from that trigger

完成标志：

- `observation_threshold -> optimizer -> proposal -> optimization task` 整条链路通过

## 约束

- 不引入新的专用调度通道
- 不让 reviewer 和 optimizer 重新混用
- 不新增第二套 proposal schema
- 不靠文档约定维持行为，必须体现在代码和测试里

## 验收标准

- optimizer 输出有唯一消费点
- `ReviewProposal.from_json_str()` 被主链实际调用
- `review_proposal_to_trigger()` 被主链实际调用
- 成功解析会生成后续优化任务
- 失败解析不会污染正常任务流
- 至少一条端到端 smoke 通过

## 建议工单名

`autonomous-review-loop-output-closure`
