# Phase 3 Step 3: Reviewer GitHub Context

日期：2026-04-03
状态：待执行
范围：`palimpsest` / `yoitsu-contracts`

## 目标

让 reviewer role 能读取 GitHub 上下文（PR/Issue 信息）并基于此进行审阅。

## 执行顺序

### Step 3.1: 定义 GitHub 上下文结构

定义传递给 reviewer 的 GitHub 上下文数据结构。

### Step 3.2: 创建 GitHub context loader

创建 context loader 从 GitHub API 获取 PR/Issue 信息。

### Step 3.3: 更新 reviewer role

让 reviewer role 使用 GitHub context loader。

## GitHub 上下文数据

### PR Context

```python
class PRContext(BaseModel):
    number: int
    title: str
    body: str
    head_branch: str
    base_branch: str
    author: str
    state: str
    files: list[str]  # Changed files
    comments: list[Comment]
```

### Issue Context

```python
class IssueContext(BaseModel):
    number: int
    title: str
    body: str
    author: str
    state: str
    labels: list[str]
    comments: list[Comment]
```

## 最小验收标准

- [ ] reviewer role 能接收 GitHub 上下文
- [ ] PR/Issue 信息能被注入到 context
- [ ] 有测试验证上下文注入
