# Phase 3 Step 2: External Trigger Ingestion

日期：2026-04-03
状态：待执行
范围：`trenni` / `yoitsu-contracts`

## 目标

让系统能接收外部事件（CI failure、label-based events）并转换为 trigger。

## 执行顺序

### Step 2.1: 定义外部事件格式

定义标准化的事件格式，用于外部系统触发任务。

### Step 2.2: 添加 External Trigger Handler

在 trenni 中添加处理外部事件的逻辑。

### Step 2.3: 事件转换

将外部事件转换为 TriggerData。

## 外部事件类型

### 1. CI Failure Event

当 CI 构建失败时触发：
```json
{
  "source": "github_actions",
  "event_type": "ci_failure",
  "repo": "owner/repo",
  "branch": "main",
  "commit_sha": "abc123",
  "workflow": "CI",
  "run_id": 12345,
  "message": "Tests failed"
}
```

### 2. Label-based Issue Event

当 Issue 被标记特定标签时触发：
```json
{
  "source": "github_issue",
  "event_type": "issue_labeled",
  "repo": "owner/repo",
  "issue_number": 42,
  "label": "needs-review",
  "title": "Bug in feature X",
  "body": "Description..."
}
```

### 3. Label-based PR Event

当 PR 被标记特定标签时触发：
```json
{
  "source": "github_pr",
  "event_type": "pr_labeled",
  "repo": "owner/repo",
  "pr_number": 42,
  "label": "ready-for-review",
  "title": "Feature: Add X",
  "head_branch": "feature/x",
  "base_branch": "main"
}
```

## 最小验收标准

- [ ] CI failure 事件能转换为 TriggerData
- [ ] Label-based 事件能转换为 TriggerData
- [ ] 有端到端测试验证转换逻辑
