# Phase 3: GitHub Client and External Trigger Ingestion

日期：2026-04-03
状态：待执行
范围：`palimpsest` / `trenni` / `yoitsu`

## 目标

统一 GitHub API 入口，接入外部协作事件。

## 执行顺序

### Step 1: 统一 GitHub Client

**目标**: 创建单一的 GitHub client，供所有组件共用。

**动作**:
1. 盘点当前 GitHub API 调用位置
   - create_pr tool
   - context loaders
   - reviewer role
2. 创建 `palimpsest/runtime/github_client.py`
3. 实现统一的 API 接口：
   - PR 创建/查询
   - Issue 评论
   - 文件读取
4. 迁移所有调用点到新 client

**完成标志**:
- GitHub client 成为唯一 GitHub API 入口
- create_pr 和 reviewer/context 不再各自拼 API

### Step 2: 外部 Trigger 接入

**目标**: 让系统能接收外部事件并转换为 trigger。

**动作**:
1. 定义外部事件格式
   - CI failure event
   - Label-based issue/PR event
2. 在 trenni 中添加 external trigger handler
3. 将外部事件转换为 TriggerData

**完成标志**:
- 至少一种外部事件能稳定转成 trigger

### Step 3: Reviewer GitHub 上下文

**目标**: 让 reviewer 能读取 GitHub 上下文。

**动作**:
1. 为 reviewer role 提供 GitHub 上下文输入
2. 实现 PR/Issue 信息注入到 context
3. 让 reviewer 能输出结构化审阅结果

**完成标志**:
- reviewer 能基于真实 GitHub 上下文工作

### Step 4: 端到端 Smoke Test

**目标**: 验证完整闭环。

**动作**:
1. 模拟外部事件
2. 触发任务
3. reviewer/join 输出结果

**完成标志**:
- external event -> task -> reviewer/join output 通过

## 最小验收标准

- [ ] GitHub client 成为唯一 GitHub API 入口
- [ ] create_pr 和 reviewer/context 不再各自拼 API
- [ ] 至少一种外部事件能稳定转成 trigger
- [ ] 有一条 external event -> task -> reviewer/join output 的 smoke path 通过
