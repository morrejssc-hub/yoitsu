# ADR 0002: Yoitsu CLI - Agent-First Stack Management

**Status:** Implemented
**Date:** 2026-03-22
**Deciders:** holo, Claude (implementation)

## Context

Yoitsu stack (pasloe + trenni) 需要频繁启停和监控以支持长时间测试。现有 `scripts/start.sh` 是面向人类的交互式脚本，不适合 agent 自动化使用。需要一个 agent-first 的 CLI 工具。

## Decision

实现 `yoitsu` CLI，提供完整的生命周期管理：

### 架构
- **Package:** 新 Python 包 `yoitsu/`，通过 `uv` 安装到 umbrella repo
- **模块划分:**
  - `process.py` - PID 文件管理、进程启停
  - `client.py` - HTTP 客户端封装（pasloe + trenni）
  - `cli.py` - Click 命令行接口

### Agent-First 设计原则
1. **JSON 输出:** 所有命令默认输出 JSON，便于解析
2. **可靠退出码:** 成功 0，失败 1
3. **幂等性:** `up` 检测已运行服务，`down` 容忍未运行状态
4. **无交互:** 无颜色、无 spinner、无提示

### 命令集
- `up` - 启动 pasloe + trenni，等待就绪
- `down` - 优雅停止（POST /control/stop → poll → SIGTERM → SIGKILL）
- `status` - 查询服务状态和统计
- `submit` - 从 YAML 批量提交任务
- `pause/resume` - 控制 trenni 调度
- `logs` - 查看服务日志

### 进程管理
- **PID 文件:** `.pids.json` 记录 pasloe + trenni PID
- **就绪检测:** `asyncio.get_running_loop().time()` 轮询，10s 超时
- **部分运行处理:** 如果只有一个服务存活，杀掉后重新启动
- **优雅关闭:** 30s 等待 → SIGTERM → SIGKILL

### 技术栈
- Python 3.11+, Click 8, httpx, PyYAML
- pytest + pytest-asyncio (>=0.23) 用于测试
- hatchling 构建后端

## Implementation

### 关键实现细节

**动态 ROOT 路径:**
```python
ROOT = Path(__file__).resolve().parent.parent
_PIDS_FILE = ROOT / ".pids.json"  # 模块级常量，支持测试 monkeypatch
```

**资源清理模式:**
```python
async def _control(endpoint):
    client = TrenniClient(url=_TRENNI_URL)
    try:
        err = await client.post_control(endpoint)
    finally:
        await client.aclose()  # 确保连接关闭
    return err
```

**类型验证:**
```python
tasks = doc["tasks"]
if not isinstance(tasks, list):
    raise ValueError(f"'tasks' must be a list, got {type(tasks).__name__}")
```

### 测试覆盖
- 37 个测试，覆盖 process、client、CLI 三层
- 使用 Click `CliRunner` + `AsyncMock` 进行集成测试
- TDD 流程：写测试 → 确认失败 → 实现 → 确认通过 → 提交

### 文档更新
- `README.md` Quick Start 更新为 `uv run yoitsu up/down/status`
- `scripts/start.sh` 添加弃用提示
- `.gitignore` 添加 `.pids.json`

## Consequences

### Positive
- Agent 可以可靠地自动化 Yoitsu 栈管理
- JSON 输出便于解析和错误处理
- 幂等命令减少状态管理复杂度
- 完整测试覆盖保证可靠性

### Negative
- 需要维护额外的 Python 包
- PID 文件方式在异常退出时可能残留（可通过 `down` 清理）

### Neutral
- 旧的 `scripts/start.sh` 保留但标记为弃用
- 虚拟环境 `.venv/` 需要在新机器上重建

## Related
- Spec: `docs/superpowers/specs/2026-03-22-yoitsu-cli-design.md` (已删除)
- Plan: `docs/superpowers/plans/2026-03-22-yoitsu-cli.md` (已删除)
- 实现提交: `8aec842` (fix), `a07c758` (docs), `a36d91f` (submit), `ce23c82` (pause/resume/logs)
