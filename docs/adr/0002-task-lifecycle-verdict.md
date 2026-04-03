# 0002: 任务生命周期与双层裁定 (Task Lifecycle & Two-Layer Verdict)

## 1. 现状与存在的问题
早期设计中，"作业完成"就等于"任务完成"——Job 退出的返回码直接决定了逻辑工作单元是否成功。这种混同导致两个严重后果：

1. 系统无法区分"代码跑完了"和"目标真正达成了"。一个 Worker 可以全部工具调用成功但其实没有解决问题。
2. 若要在执行器内部嵌入质量评估逻辑，会让 Palimpsest 变成一个同时承担执行与裁判职能的复杂体，打破短命无状态的设计。

## 2. 做出的决策与原因

### 2a. Task 状态机
```
pending → running → evaluating → completed
                              → failed
                              → partial
                              → cancelled
                              → eval_failed
```
- **evaluating** 是 Trenni 在所有生产性 Job 结构完成后的显式中间态，不可跳过。
- **partial** 仅在预算耗尽且发布成功时产生——代表"做了有意义的工作但目标未达成"。
- **eval_failed** 代表评估 Job 自身出错，Task 以仅有结构裁定的方式终结。

### 2b. 双层裁定
每个终结 Task 携带两个独立层次的结论：

- **结构裁定 (Structural Verdict)**：由 Trenni 根据 Job 终端状态确定性计算，不涉及大模型。它回答"跑了什么、结果是什么"，**始终存在**。
- **语义裁定 (Semantic Verdict)**：由独立的 Eval Job 产出——对原始目标的质量判断（`pass / fail / unknown`）。它回答"目标达成了吗"，**可选**。

**原因**：将质量判定从执行体中彻底剥离出来。结构裁定保证即使 Eval 出错、超时、甚至未配置，系统也不会进入信息黑洞。语义裁定则把"好不好"的判断交给专门的外部角色，使得 Evaluator 可以独立测试、替换与演化。

### 2c. Eval 由 Spawn 时的 Planner 指定
`eval_spec`（交付物与验证标准）不在 Trigger 时指定，而是在 Planner 分解 Task 后通过 `SpawnRequestData` 携带。**原因**：只有 Planner 在理解目标后，才知道该检查什么。

### 2d. Idle Detection 替代 `task_complete` 工具
Job 退出不依赖 Agent 主动调用"结束"工具（已移除），而是由运行时检测 LLM 连续两轮不调用工具来判定空闲退出。**原因**：`task_complete` 让 Agent 自行报告"我完成了"，引入了 Task 与 Job 语义的混淆，且模型自报告不可靠。Idle Detection 将退出判定交还给运行时，从行为层面观察。

## 3. 期望达到的结果
- 任何 Task 都不会以信息完全丢失的方式终结，至少存在结构裁定。
- 质量评估与执行完全解耦，Evaluator 角色可独立测试和替换。
- 父级 Join Job 在汇总时可以同时获取所有子 Task 的结构与语义裁定做综合决策。

## 4. 容易混淆的概念
- **结构完成 (Structural Completion) vs 语义完成 (Semantic Completion)**
  - 所有 Job 跑完 = 结构完成。Eval Job 返回 `pass` = 语义完成。两者独立且可以不一致。
- **partial vs failed**
  - `partial`：Agent 因预算耗尽退出，但产物已成功发布（有价值的半成品）。
  - `failed`：主动报错或发布失败（无可用产物）。

## 5. 对之前 ADR 或文档的修正说明
本 ADR 取代归档版 ADR-0002 的完整内容。Idle Detection 行为的代码实现细节参见 `palimpsest/stages/interaction.py`。
