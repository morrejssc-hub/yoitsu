# Phase 2: Observation Loop Closure

日期：2026-04-03
状态：待执行
范围：`pasloe` / `trenni` / `palimpsest` / `yoitsu-contracts`

## 目标

把 ADR-0010 里"结构化信号 -> Review Task -> Proposal -> 优化 Task"的闭环真正打通。

## 执行顺序

按下面顺序推进，不要乱序：

### Step 1: 定 observation 读模型

**目标**: 在 Pasloe 里先补时间窗口和聚合查询接口，把"Review Task 需要看到什么"定成稳定返回结构。

**动作**:
- 盘点 Pasloe 当前查询能力
- 定义 Review Task 需要的聚合查询：
  - 预算消耗率 (budget_variance 累积)
  - 任务成功率/失败率
  - 迭代次数分布
- 实现时间窗口查询 (最近 N 小时/天)
- 实现聚合查询接口

**完成标志**:
- Pasloe 提供稳定的聚合查询返回结构
- Review Task 能通过 API 读取结构化信号

### Step 2: 补发射面

**目标**: 盘点并补齐 observation.* 信号，确保信号足够稳定。

**动作**:
- 盘点现有 observation.* 事件：
  - trenni 发射的信号
  - palimpsest 发射的信号
  - tool gateway 发射的信号
- 补齐缺口：
  - budget_variance (ADR-0010 D5)
  - iteration_count
  - task_outcome
- 只发确定性信号，不引入模型解释

**完成标志**:
- 关键路径都有结构化 observation 信号
- 信号字段稳定、可聚合

### Step 3: 激活闭环

**目标**: 让 observation 真能驱动 Review Task 产生。

**动作**:
- 实现累积阈值触发逻辑
- 让 Review Task 读取聚合结果
- 补端到端 smoke：
  - observation 累积
  - trigger 触发 review task
  - review task 读取聚合上下文

**完成标志**:
- review task 不再只是概念存在
- 系统健康的核心代理指标是预算预测精度

## 约束

- 不先做 trigger 再回头补查询接口
- 只发确定性信号，不引入模型解释
- 聚合查询返回结构要稳定，供 Review Task 消费

## 验收方式

- Pasloe 聚合查询接口可用
- observation.* 信号覆盖关键路径
- smoke path: observation -> accumulate -> review task 通过