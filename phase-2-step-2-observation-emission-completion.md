# Phase 2 Step 2: Observation Emission Completion

日期：2026-04-03
状态：待执行
范围：`trenni` / `palimpsest` / `yoitsu-contracts`

## 目标

补齐 observation.* 信号发射，确保 Review Task 能读到结构化信号。

## 执行顺序

### Step 2.1: 发射点盘点

列出当前所有 observation.* 的实际发射位置：

| 信号 | Owner | 状态 | 发射位置 |
|------|-------|------|----------|
| `observation.budget_variance` | trenni | 已发射 | supervisor._emit_budget_variance |
| `observation.preparation_failure` | palimpsest | 仅有 schema | - |
| `observation.tool_retry` | tool gateway | 仅有 schema | - |

### Step 2.2: 补齐确定性发射

按优先级补齐：

1. **budget_variance**: 确认 job 完成后稳定发射
2. **preparation_failure**: 补发射点
3. **tool_retry**: 补发射点

原则：一条信号只对应一个机械事实，不混入模型判断。

### Step 2.3: 闭环验证

- 发出事件
- 通过新 observation API 读到 detail
- 通过 aggregate / by_role 聚合读到结果
- 补一条端到端 smoke

## 最小验收标准

- budget_variance 发射路径有回归测试
- preparation_failure 和 tool_retry 至少各有一个稳定发射点
- 三类 observation 都能被 Pasloe 新接口读到
- 至少一条聚合查询测试通过