# Phase 3 Step 4: End-to-End Smoke Test

日期：2026-04-03
状态：待执行
范围：`trenni` / `palimpsest` / `yoitsu-contracts`

## 目标

验证完整的外部事件闭环：external event -> trigger -> task -> output。

## 测试场景

### 场景 1: PR Labeled -> Reviewer Task

1. 接收 `pr_labeled` 外部事件
2. 转换为 TriggerData
3. 触发 reviewer role 任务
4. reviewer 能访问 GitHub 上下文

### 场景 2: Issue Labeled -> Reviewer Task

1. 接收 `issue_labeled` 外部事件
2. 转换为 TriggerData
3. 触发 reviewer role 任务
4. reviewer 能访问 GitHub 上下文

## 最小验收标准

- [ ] 外部事件能触发任务创建
- [ ] GitHub 上下文能传递到 role
- [ ] 端到端测试通过
