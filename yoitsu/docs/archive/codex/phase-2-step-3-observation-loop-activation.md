# Phase 2 Step 3: Observation Loop Activation

日期：2026-04-03
状态：待执行
范围：`pasloe` / `trenni` / `palimpsest`

## 目标

验证 observation 闭环：发射 -> 存储 -> 聚合查询。

## 执行顺序

### Step 3.1: 验证事件存储

确认 observation.* 事件能被 Pasloe 存储到 detail 表。

### Step 3.2: 验证聚合查询

确认聚合查询 API 返回正确结果。

### Step 3.3: 端到端 smoke test

完整闭环验证：
1. 模拟 job 完成，发射 budget_variance
2. Pasloe 存储事件到 detail 表
3. 通过聚合 API 读取结果

## 最小验收标准

- observation 事件能被 Pasloe 存储
- 聚合查询返回正确的统计数据
- 端到端测试通过
